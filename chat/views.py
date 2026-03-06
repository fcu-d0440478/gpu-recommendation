"""
API Views：
- POST /api/chat — 接收訊息，呼叫 skill + Ollama，回傳推薦
- POST /api/update-db — 觸發 ETL 更新
- GET  /api/db-meta — 回傳 DB 狀態資訊
- GET  /api/db-browse — 瀏覽最新日期資料（支援搜尋、排序）
- GET  / — 主頁面（聊天 UI）
"""
import json
import logging

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from chat.llm_client import LLMClient
from chat.skills import (
    skill_get_gpu_recommendations,
    skill_get_db_meta,
    skill_search_gpu_candidates,
    skill_update_database,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一個專業的顯示卡推薦助手。

嚴格規則：
1. 你只使用系統提供的資料庫查詢結果，絕對不可虛構任何規格、價格或分數。
2. 【重要】絕對不可以詢問使用者任何問題。資料已由系統查詢完畢，直接根據資料推薦。
3. 必須立即給出推薦，不得要求確認或追問用途。
4. 全程使用繁體中文。

CP 值 = UL TimeSpy 跑分 / 台幣售價，CP 值越高代表同預算效能越好。"""


import re

_ZH_DIGIT = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_ZH_UNIT = {"十": 10, "百": 100, "千": 1000, "萬": 10000}

def _parse_zh_int_upto_9999(s: str) -> int | None:
    if not s:
        return None

    total = 0
    num = None
    unit_seen = False

    for ch in s:
        if ch in _ZH_DIGIT:
            num = _ZH_DIGIT[ch]
        elif ch in _ZH_UNIT and ch != "萬":
            unit_seen = True
            unit = _ZH_UNIT[ch]
            if num is None:
                num = 1
            total += num * unit
            num = None
        else:
            return None

    if num is not None:
        total += num

    return total if (total > 0 or unit_seen or num == 0) else None

def parse_zh_amount(text: str) -> int | None:
    t = text.strip().replace(",", "").replace(" ", "")
    if not t:
        return None

    m = re.fullmatch(r"\d+", t)
    if m:
        return int(t)

    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*萬", t)
    if m:
        return int(float(m.group(1)) * 10000)

    m = re.fullmatch(r"(\d+)\s*萬\s*(\d+)?\s*(千)?", t)
    if m:
        wan = int(m.group(1)) * 10000
        tail = m.group(2)
        has_qian = m.group(3) is not None
        if not tail:
            return wan + (1000 if has_qian else 0)
        tail_num = int(tail)
        if has_qian:
            return wan + tail_num * 1000
        if len(tail) == 1:
            return wan + tail_num * 1000
        if len(tail) >= 3:
            return wan + tail_num
        return wan + tail_num * 100

    if "萬" in t:
        parts = t.split("萬", 1)
        left = parts[0]
        right = parts[1].strip()
        
        left_val = _parse_zh_int_upto_9999(left)
        if left_val is None:
            return None
        base = left_val * 10000

        if not right:
            return base

        right_val = _parse_zh_int_upto_9999(right.replace("千", "千"))
        if right_val is not None:
            if right_val < 10 and ("千" not in right) and ("百" not in right) and ("十" not in right):
                return base + right_val * 1000
            return base + right_val

        m2 = re.fullmatch(r"(\d+)", right)
        if m2:
            tail_num = int(m2.group(1))
            if len(m2.group(1)) == 1:
                return base + tail_num * 1000
            return base + tail_num
        return None

    val = _parse_zh_int_upto_9999(t)
    if val is not None:
        return val

    return None

def _extract_intent(message: str) -> dict:
    """
    從使用者訊息中提取意圖：預算或目標顯卡。
    使用規則提取，不呼叫 LLM。
    """
    budget = None
    target_gpu = None

    # 先找 GPU 型號（需優先偵測，避免型號中的數字被誤判為預算）
    gpu_keywords = [
        r"(?<![a-zA-Z])RTX\s*\d+[A-Za-z0-9]*(?:\s+(?:Ti|SUPER|XT|XTX|GRE))?(?:\s+SUPER)?",
        r"(?<![a-zA-Z])RX\s*\d+[A-Za-z0-9]*(?:\s+(?:Ti|SUPER|XT|XTX|GRE))?(?:\s+SUPER)?",
        r"(?<![a-zA-Z])Arc\s*[AB]\d+[A-Za-z0-9]*",
        r"(?<![a-zA-Z])GTX\s*\d+[A-Za-z0-9]*(?:\s+(?:Ti|SUPER|XT|XTX|GRE))?(?:\s+SUPER)?",
    ]
    gpu_match_span = None
    for pattern in gpu_keywords:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            target_gpu = match.group(0).strip()
            gpu_match_span = match.span()
            break

    search_text = message
    if gpu_match_span:
        start, end = gpu_match_span
        search_text = message[:start] + ' ' * (end - start) + message[end:]

    # 抓取包含「數字/中文數字」等片段丟給 parser 處理
    cand_matches = re.finditer(r"([零〇一二兩三四五六七八九十百千萬\d\.,\s]{1,15})(?:元|塊|台幣|twd|左右|以內|內)?", search_text, re.IGNORECASE)
    for cand in cand_matches:
        amt = parse_zh_amount(cand.group(1))
        # 通常合理預算在 3000 ~ 300000 之間
        if amt and 3000 <= amt <= 300000:
            budget = amt
            break

    # 判斷是否為更新資料庫的意圖
    update_keywords = ["更新", "刷新", "同步", "爬取"]
    is_update = bool(re.search(r"\bupdate\b|\brefresh\b", message, re.IGNORECASE)) or any(kw in message for kw in update_keywords)

    return {
        "budget": budget,
        "target_gpu": target_gpu,
        "is_update": is_update,
    }



def index(request):
    """主頁面"""
    meta = skill_get_db_meta()
    return render(request, "chat/index.html", {"db_meta": meta})


@csrf_exempt
@require_http_methods(["POST"])
def api_chat(request):
    """
    POST /api/chat
    接收 JSON {message: "..."}，回傳推薦結果。
    """
    try:
        body = json.loads(request.body)
        message = body.get("message", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "無效的請求格式"}, status=400)
    
    if not message:
        return JsonResponse({"error": "請輸入訊息"}, status=400)
    
    logger.info(f"收到訊息：{message}")
    
    # 提取意圖
    intent = _extract_intent(message)
    
    # 若為更新請求，不走推薦流程
    if intent["is_update"]:
        return JsonResponse({
            "assistant_message": "請點擊「更新資料庫」按鈕來同步最新資料。",
            "recommendations": [],
            "base_price": None,
            "window_used_pct": None,
            "latest_date": None,
        })
    
    budget = intent["budget"]
    target_gpu = intent["target_gpu"]

    # 若有 target_gpu，強制忽略 budget（避免型號數字如 '5060' 被誤判為預算）
    if target_gpu is not None:
        budget = None
    
    # 若無預算也無目標卡，直接回傳固定提示（不呼叫 LLM 避免模型亂問）
    if budget is None and target_gpu is None:
        return JsonResponse({
            "assistant_message": "請告訴我您的預算（例如：預算 15000 元）或目標顯卡型號（例如：RTX 5060），我會立即從最新資料庫查詢 CP 值最高的 Top 3 推薦！",
            "recommendations": [],
            "base_price": None,
            "window_used_pct": None,
            "latest_date": None,
        })
    
    # 呼叫 skill 查詢推薦
    result = skill_get_gpu_recommendations(
        budget_twd=budget,
        target_gpu=target_gpu,
        price_window_pct=0.10,
        top_k=3,
    )
    
    if "error" in result:
        return JsonResponse({
            "assistant_message": f"抱歉，{result['error']}",
            "recommendations": [],
            "base_price": budget,
            "window_used_pct": None,
            "latest_date": None,
        })
    
    recommendations = result.get("recommendations", [])
    target_gpu_info = result.get("target_gpu_info")   # 比較模式才有
    base_price = result.get("base_price")
    window_pct = result.get("window_used_pct", 10)
    latest_date = result.get("latest_date")
    
    # 建立推薦資料的 prompt
    recs_text = "\n".join([
        f"- {r['product']}（{r['pure_chipset']}）\n"
        f"  價格：${r['price']:,}｜分數：{r['score']:,}｜CP 值：{r['CP']:.4f}"
        for r in recommendations
    ])
    
    # 計算價差百分比
    for rec in recommendations:
        diff = rec["price"] - base_price
        rec["price_diff_pct"] = f"{'+' if diff >= 0 else ''}{diff/base_price*100:.1f}%"
        rec["name"] = rec.get("pure_chipset", rec.get("product", ""))
        rec["cp"] = rec.get("CP", 0)
        rec["reason"] = ""

    # 若無推薦資料，直接回傳不呼叫 LLM
    if not recommendations:
        is_compare_mode = (target_gpu is not None)
        if is_compare_mode:
            assistant_msg = f"抱歉，資料庫中目前找不到與 {target_gpu} 價格（${base_price:,}）相近且效能相當的替代顯示卡。這可能是因為該型號在這價位帶已經沒有更具 CP 值的競爭對手，或者資料庫缺少相關報價。建議您嘗試比較其他型號，或更新資料庫。"
        else:
            assistant_msg = f"抱歉，資料庫中目前找不到價格在 ${base_price:,} 元附近範圍內的顯示卡。建議調整預算範圍或重新更新資料庫。"
            
        return JsonResponse({
            "assistant_message": assistant_msg,
            "recommendations": [],
            "base_price": base_price,
            "window_used_pct": window_pct,
            "latest_date": latest_date,
        })

    # ── 比較模式 vs 預算模式 ───────────────────────────────────────
    is_compare_mode = (target_gpu is not None)

    if is_compare_mode and target_gpu_info:
        tgi = target_gpu_info
        target_line = (
            f"【目標卡】{tgi['product']}（{tgi['pure_chipset']}）"
            f"｜售價：${tgi['price']:,}｜跑分：{tgi['score']:,}｜CP 值：{tgi['CP']:.4f}"
        )
        alt_lines = "\n".join([
            f"{i+1}. {r['product']}（{r['pure_chipset']}）"
            f"｜售價：${r['price']:,}｜跑分：{r['score']:,}｜CP 值：{r['CP']:.4f}｜價差：{r['price_diff_pct']}"
            for i, r in enumerate(recommendations)
        ])
        prompt = f"""【資料庫查詢完畢，請立即分析，不得提問】

使用者要比較：{tgi['pure_chipset']} 和同價位的選擇
資料日期：{latest_date}，比較範圍 ±{window_pct}%

{target_line}

同價位替代方案（依 CP 值排序）：
{alt_lines}

請直接輸出比較分析：
1. 目標卡（{tgi['pure_chipset']}）CP 值評價——在同價位中是否划算？
2. 替代方案中哪張卡 CP 值更高？優勢在哪？
3. 最終建議：是否值得換成替代方案？

不得詢問使用者任何問題，直接給出結論。"""
        # 比較模式：將目標卡也放入前端卡片（標記 is_target）
        target_card = dict(tgi)
        target_card["price_diff_pct"] = "±0%（目標卡）"
        target_card["name"] = tgi.get("pure_chipset", tgi.get("product", ""))
        target_card["cp"] = tgi.get("CP", 0)
        target_card["reason"] = ""
        target_card["is_target"] = True
        all_cards = recommendations + [target_card]
    else:
        # 預算模式：純推薦
        recs_text_lines = "\n".join([
            f"{i+1}. {r['product']}（{r['pure_chipset']}）｜售價：${r['price']:,}｜跑分：{r['score']:,}｜CP 值：{r['CP']:.4f}｜與預算差距：{r['price_diff_pct']}"
            for i, r in enumerate(recommendations)
        ])
        prompt = f"""【資料庫查詢完畢，請立即根據以下資料給出推薦，不得提問】

查詢條件：預算 ${base_price:,} 元，價格範圍 ±{window_pct}%
資料日期：{latest_date}

查詢結果（已依 CP 值排序）：
{recs_text_lines}

請直接輸出：
1. 推薦結論（Top 1 是什麼，CP 值最高的理由）
2. 各卡推薦理由（CP 值、與預算的差距、是否划算）
3. 總結建議

不得詢問使用者任何問題，直接給出分析結果。"""
        all_cards = recommendations

    # ── 呼叫 LLM ──────────────────────────────────────────────
    client = LLMClient()
    try:
        assistant_message = client.generate(prompt, system=SYSTEM_PROMPT)
    except RuntimeError:
        lines = [
            f"{i+1}. {r['product']}\n   售價：${r['price']:,} | 跑分：{r['score']:,} | CP 值：{r['CP']:.4f}"
            for i, r in enumerate(recommendations)
        ]
        assistant_message = "（LLM 服務暫時無法連線）\n\n查詢結果如下：\n" + "\n".join(lines)

    return JsonResponse({
        "assistant_message": assistant_message,
        "recommendations": all_cards,
        "base_price": base_price,
        "window_used_pct": window_pct,
        "latest_date": latest_date,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_update_db(request):
    """
    POST /api/update-db
    觸發 ETL 更新（含節流保護）。
    """
    try:
        body = json.loads(request.body) if request.body else {}
        force = body.get("force", False)
    except json.JSONDecodeError:
        force = False
    
    try:
        result = skill_update_database(force=force)
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"ETL 更新失敗：{e}")
        return JsonResponse({"status": "error", "reason": str(e)}, status=500)


@require_http_methods(["GET"])
def api_db_meta(request):
    """
    GET /api/db-meta
    回傳最後更新時間、來源、顯示卡數量。
    """
    meta = skill_get_db_meta()
    return JsonResponse(meta)


@require_http_methods(["GET"])
def api_db_browse(request):
    """
    GET /api/db-browse
    回傳最新日期的顯示卡資料，支援搜尋、排序、價格範圍過濾與分頁。
    Query params:
      - search     : 關鍵字，比對 product / pure_chipset（可選）
      - sort       : 排序欄位，合法值 price|score|CP|chipset|product|pure_chipset，預設 CP
      - order      : asc|desc，預設 desc
      - price_min  : 最低售價（整數，可選）
      - price_max  : 最高售價（整數，可選）
      - page       : 頁碼（從 1 開始），預設 1
      - page_size  : 每頁筆數，固定 50
    """
    import sqlite3
    from django.conf import settings as django_settings

    PAGE_SIZE = 50

    # ── 白名單防 SQL Injection（含文字欄位）──
    ALLOWED_SORT = {"price", "score", "CP", "chipset", "product", "pure_chipset"}
    sort_col = request.GET.get("sort", "CP")
    if sort_col not in ALLOWED_SORT:
        sort_col = "CP"

    order = request.GET.get("order", "desc").lower()
    if order not in ("asc", "desc"):
        order = "desc"

    search = request.GET.get("search", "").strip()

    # 價格範圍
    def _to_int(val):
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    price_min = _to_int(request.GET.get("price_min"))
    price_max = _to_int(request.GET.get("price_max"))

    # 分頁
    page = max(1, _to_int(request.GET.get("page")) or 1)

    db_path = str(django_settings.GPU_DB_PATH)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 取最新日期
        cursor.execute("SELECT MAX(date) FROM filtered_df")
        row = cursor.fetchone()
        latest_date = row[0] if row else None

        if not latest_date:
            return JsonResponse({
                "rows": [], "total": 0, "total_pages": 0,
                "page": 1, "page_size": PAGE_SIZE, "latest_date": None,
            })

        # 建立查詢（欄位名稱已白名單化，直接嵌入）
        base_sql = (
            "SELECT date, chipset, product, price, pure_chipset, score, CP "
            "FROM filtered_df "
            "WHERE date = ? "
        )
        params = [latest_date]

        if search:
            base_sql += "AND (product LIKE ? OR pure_chipset LIKE ?) "
            like = f"%{search}%"
            params += [like, like]

        if price_min is not None:
            base_sql += "AND price >= ? "
            params.append(price_min)

        if price_max is not None:
            base_sql += "AND price <= ? "
            params.append(price_max)

        # 文字欄位排序加 COLLATE NOCASE，數值欄位直接排序
        if sort_col in ("chipset", "product", "pure_chipset"):
            base_sql += f"ORDER BY {sort_col} COLLATE NOCASE {order.upper()}"
        else:
            base_sql += f"ORDER BY {sort_col} {order.upper()}"

        cursor.execute(base_sql, params)
        rows_raw = cursor.fetchall()
        conn.close()

        all_rows = [
            {
                "date": r["date"],
                "chipset": r["chipset"],
                "product": r["product"],
                "price": r["price"],
                "pure_chipset": r["pure_chipset"],
                "score": r["score"],
                "CP": round(r["CP"], 4) if r["CP"] is not None else None,
            }
            for r in rows_raw
        ]

        total = len(all_rows)
        import math
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, total_pages)

        start = (page - 1) * PAGE_SIZE
        rows = all_rows[start: start + PAGE_SIZE]

        return JsonResponse({
            "rows": rows,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "page_size": PAGE_SIZE,
            "latest_date": latest_date,
        })

    except Exception as e:
        logger.error(f"DB 瀏覽查詢失敗：{e}")
        return JsonResponse({"error": str(e)}, status=500)
