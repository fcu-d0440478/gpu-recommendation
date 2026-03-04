"""
API Views：
- POST /api/chat — 接收訊息，呼叫 skill + Ollama，回傳推薦
- POST /api/update-db — 觸發 ETL 更新
- GET  /api/db-meta — 回傳 DB 狀態資訊
- GET  / — 主頁面（聊天 UI）
"""
import json
import logging

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from chat.ollama_client import OllamaClient
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


def _extract_intent(message: str) -> dict:
    """
    從使用者訊息中提取意圖：預算或目標顯卡。
    使用規則提取，不呼叫 LLM。
    """
    import re

    budget = None

    # 先找 GPU 型號（需優先偵測，避免型號中的數字被誤判為預算）
    target_gpu = None
    gpu_keywords = [
        r"RTX\s*\d+\w*",
        r"RX\s*\d+\w*",
        r"Arc\s*[AB]\d+",
        r"GTX\s*\d+\w*",
    ]
    gpu_match_span = None  # 記錄 GPU 型號在字串中的位置，之後排除這段數字
    for pattern in gpu_keywords:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            target_gpu = match.group(0).strip()
            gpu_match_span = match.span()  # (start, end)
            break

    # 提取預算：需排除 GPU 型號所在的子字串
    search_text = message
    if gpu_match_span:
        # 用空格替換 GPU 型號，避免其中的數字被當預算
        start, end = gpu_match_span
        search_text = message[:start] + ' ' * (end - start) + message[end:]

    # 先嘗試帶千位分隔符的格式（15,000）
    match = re.search(r"\b(\d{1,3}(?:,\d{3})+)\s*(?:元|塊|台幣|twd)?\b", search_text, re.IGNORECASE)
    if match:
        num_str = match.group(1).replace(",", "")
        num = int(num_str)
        if 3000 <= num <= 300000:
            budget = num

    # 再嘗試純數字格式（用 \b 確保匹配完整數字）
    if not budget:
        for m in re.finditer(r"\b(\d+)\b", search_text):
            num = int(m.group(1))
            if 3000 <= num <= 300000:
                budget = num
                break

    # 萬元格式（1萬5、1.5萬）
    if not budget:
        match = re.search(r"(\d+(?:\.\d+)?)\s*萬\s*(\d*)", search_text)
        if match:
            wan = float(match.group(1))
            extra = int(match.group(2)) * 1000 if match.group(2) else 0
            budget = int(wan * 10000) + extra

    # 判斷是否為更新資料庫的意圖
    update_keywords = ["更新", "刷新", "同步", "爬取", "update"]
    is_update = any(kw in message.lower() for kw in update_keywords)

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
        return JsonResponse({
            "assistant_message": f"抱歉，資料庫中目前找不到價格在 ${base_price:,} 元 ±{window_pct}% 範圍內的顯示卡。建議調整預算範圍或重新更新資料庫。",
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

    # ── 呼叫 Ollama ──────────────────────────────────────────────
    client = OllamaClient()
    try:
        assistant_message = client.generate(prompt, system=SYSTEM_PROMPT)
    except RuntimeError:
        lines = [
            f"{i+1}. {r['product']}\n   售價：${r['price']:,} | 跑分：{r['score']:,} | CP 值：{r['CP']:.4f}"
            for i, r in enumerate(recommendations)
        ]
        assistant_message = "（Ollama 服務暫時無法連線）\n\n查詢結果如下：\n" + "\n".join(lines)

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
