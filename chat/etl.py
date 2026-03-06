"""
ETL 模組：爬取 CoolPC + UL Benchmark，LLM 自動 Mapping，清洗資料並寫入 filtered_df.db
"""
import json
import logging
import re
import sqlite3
import html
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

FILTER_KEYWORDS = [
    "贈", "抽", "送", "加購", "登錄", "活動", "限量", "現省",
    "現折", "現賺", "再加", "加送", "加價購", "[合購]", "[紅包",
]

BLACKLIST_CHIPSETS_PATTERNS = [
    "Quadro", "工作站", "專業繪圖", "配件", "轉接",
]


def _get_gpu_db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.GPU_DB_PATH))
    return conn


def _load_mapping() -> dict:
    """載入 GPU Mapping JSON"""
    path = Path(str(settings.GPU_MAPPING_JSON_PATH))
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_mapping(mapping: dict):
    """儲存 GPU Mapping JSON（不覆蓋已有 key）"""
    path = Path(str(settings.GPU_MAPPING_JSON_PATH))
    existing = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    # 合併：現有 key 優先
    merged = {**mapping, **existing}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)


def crawl_coolpc() -> list[dict]:
    """
    爬取 CoolPC 原價屋 evaluate.php VGA 分類。
    參照 1 wayback_vga_tracker.py 的邏輯，改為爬取「即時頁面」。
    回傳 [{chipset, product, price}]
    """
    results = []
    try:
        url = "https://www.coolpc.com.tw/evaluate.php"
        logger.info(f"正在爬取 CoolPC：{url}")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        resp.encoding = "big5"
        page = resp.text
        select_match = re.search(
            r"<select[^>]*\bname\s*=\s*(?:[\"']?n12[\"']?)\b[^>]*>",
            page,
            flags=re.IGNORECASE,
        )
        if select_match is None:
            raise RuntimeError("找不到 CoolPC 顯示卡下拉選單（n12）")

        select_end = page.lower().find("</select>", select_match.end())
        if select_end == -1:
            raise RuntimeError("CoolPC 顯示卡下拉選單格式異常（缺少 </select>）")

        vga_segment = page[select_match.end():select_end]
        token_pattern = re.compile(
            r"<optgroup[^>]*label\s*=\s*(?:[\"']([^\"']*)[\"']|([^\s>]+))[^>]*>"
            r"|<option[^>]*>(.*?)</option>",
            flags=re.IGNORECASE | re.DOTALL,
        )

        chipset = ""
        for token in token_pattern.finditer(vga_segment):
            label = token.group(1) or token.group(2)
            if label is not None:
                chipset = html.unescape(label).strip()
                continue

            option_html = token.group(3) or ""
            text = " ".join(re.sub(r"<[^>]+>", "", html.unescape(option_html)).split())
            if not text:
                continue
            if not chipset:
                continue
            match = re.search(r"(.+?),?\s*\$([\d,]+)", text)
            if match:
                product = match.group(1).strip()
                price = int(match.group(2).replace(",", ""))
                results.append({"chipset": chipset, "product": product, "price": price})

        logger.info(f"CoolPC 爬取完成，共 {len(results)} 筆")
    except Exception as e:
        logger.error(f"CoolPC 爬取失敗：{e}")
        raise
    return results


def crawl_ul_benchmark() -> list[dict]:
    """
    爬取 UL Benchmark GPU 分數頁面。
    參照 2 gpu_scraper_ul.py 的邏輯。
    回傳 [{name, score}]，同名取最高分。
    """
    results = []
    try:
        url = (
            "https://benchmarks.ul.com/compare/best-gpus"
            "?amount=0&sortBy=SCORE&reverseOrder=true&types=DESKTOP&minRating=0"
        )
        logger.info(f"正在爬取 UL Benchmark：{url}")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("table tbody tr")
        logger.info(f"找到 {len(rows)} 筆 GPU 資料")

        for index, row in enumerate(rows, start=1):
            try:
                cols = row.find_all("td")
                if len(cols) < 4:
                    raise ValueError("欄位不足")
                gpu_name = cols[1].get_text(strip=True)
                score_text = cols[3].get_text(strip=True).replace(",", "")
                gpu_score = int(score_text)
                results.append({"name": gpu_name, "score": gpu_score})
            except Exception as e:
                logger.warning(f"第 {index} 筆 UL 資料解析失敗：{e}")
                continue

        logger.info(f"UL Benchmark 爬取完成，共 {len(results)} 筆")
    except Exception as e:
        logger.error(f"UL Benchmark 爬取失敗：{e}")
        raise

    # 同名取最高分並去重
    if results:
        df = pd.DataFrame(results)
        df = df.sort_values("score", ascending=False).drop_duplicates(subset="name", keep="first")
        results = df.to_dict(orient="records")
    return results


def llm_map_chipsets(unknown_chipsets: list[str], ul_gpu_names: list[str]) -> dict:
    """
    呼叫 Groq（llama-3.1-8b-instant）批次對應未知 chipset 到 UL 標準名稱。
    回傳 {chipset: ul_name_or_null}
    """
    from chat.llm_client import LLMClient

    client = LLMClient()

    system_prompt = """你是 GPU 型號對應專家。請將 CoolPC 原價屋的顯卡分類名稱（chipset）
對應到以下標準 GPU 型號列表（來自 UL Benchmark）。

對應規則：
1. 提取核心型號，例如：
   - "AMD Radeon RX9060XT-8G" → "AMD Radeon RX 9060 XT"
   - "NVIDIA RTX4070-12G" → "NVIDIA GeForce RTX 4070"
   - "INTEL Arc B580" → "Intel Arc B580"
2. 以下類型對應到 null：
   - 配件、轉接盒、周邊
   - 專業繪圖卡（Quadro、工作站級）
3. 必須使用標準 GPU 型號列表中的完整名稱，不可自行創造
4. 只輸出 JSON 物件，不要任何其他文字"""

    ul_names_json = json.dumps(ul_gpu_names, ensure_ascii=False)
    unknown_json = json.dumps(unknown_chipsets, ensure_ascii=False)

    prompt = f"""標準 GPU 型號列表：
{ul_names_json}

待對應的 chipset 列表：
{unknown_json}

輸出格式：{{"chipset名稱": "標準GPU名稱或null"}}"""

    try:
        result = client.generate_json(prompt, system_prompt)
        # 驗證：value 必須存在於 UL 清單中或為 null
        validated = {}
        for k, v in result.items():
            if v is None or v in ul_gpu_names:
                validated[k] = v
            else:
                logger.warning(f"LLM 回傳的 GPU 名稱不在 UL 清單中，設為 null：{v}")
                validated[k] = None
        return validated
    except Exception as e:
        logger.error(f"LLM Mapping 失敗：{e}")
        # 發生錯誤時回傳空字典，不要存死 null，讓下次再試
        return {}


def clean_and_calculate_cp(coolpc_data: list[dict], mapping: dict, ul_df: pd.DataFrame) -> pd.DataFrame:
    """
    清洗並計算 CP 值。
    參照 4 pre_process_data.ipynb 的邏輯。
    """
    df = pd.DataFrame(coolpc_data)

    # 過濾含特殊關鍵字的 product
    filter_pattern = "|".join(re.escape(k) for k in FILTER_KEYWORDS)
    df = df[~df["product"].str.contains(filter_pattern, na=False)]

    # 過濾黑名單 chipset
    blacklist_pattern = "|".join(BLACKLIST_CHIPSETS_PATTERNS)
    df = df[~df["chipset"].str.contains(blacklist_pattern, na=False)]

    # 套用 mapping 轉換 pure_chipset
    df["pure_chipset"] = df["chipset"].map(mapping)

    # 僅保留有 pure_chipset 的資料（null 或不在 mapping 中都剔除）
    df = df[df["pure_chipset"].notna()]

    # 合併 UL 分數
    df = df.merge(ul_df[["name", "score"]], left_on="pure_chipset", right_on="name", how="left")
    df = df.drop(columns=["name"], errors="ignore")

    # 僅保留有分數的資料
    df = df[df["score"].notna()]
    df["score"] = df["score"].astype(int)

    # 計算 CP
    df["CP"] = df["score"] / df["price"]
    df["CP"] = df["CP"].round(4)

    logger.info(f"清洗後剩餘 {len(df)} 筆資料")
    return df


def run_etl(force: bool = False) -> dict:
    """
    ETL 主流程：
    1. 爬取 CoolPC + UL Benchmark
    2. LLM 自動 Mapping
    3. 清洗 + CP 計算
    4. 寫入 filtered_df.db

    Args:
        force: 若 True，即使今天已更新也重新執行

    Returns:
        結果 dict
    """
    today = datetime.now().strftime("%Y%m%d")

    # 節流：同一天不重複更新
    if not force:
        conn = _get_gpu_db_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM filtered_df WHERE date = ?", [today])
            count = cursor.fetchone()[0]
            if count > 0:
                logger.info(f"今天 ({today}) 已有資料，跳過 ETL（使用 force=True 強制更新）")
                return {"status": "skipped", "reason": f"今天 ({today}) 已有資料，無需重複更新", "date": today}
        except Exception:
            pass
        finally:
            conn.close()

    logger.info("=== 開始 ETL 流程 ===")

    # Step 1：爬取資料
    logger.info("Step 1：爬取 CoolPC 資料...")
    coolpc_data = crawl_coolpc()

    logger.info("Step 1：爬取 UL Benchmark 資料...")
    ul_data = crawl_ul_benchmark()
    ul_df = pd.DataFrame(ul_data)
    ul_gpu_names = ul_df["name"].tolist() if not ul_df.empty else []

    # Step 2：LLM Mapping
    logger.info("Step 2：LLM 自動 Mapping...")
    mapping = _load_mapping()

    # 找出未知的 chipset
    all_chipsets = list({row["chipset"] for row in coolpc_data})
    unknown_chipsets = [c for c in all_chipsets if c not in mapping]

    if unknown_chipsets:
        logger.info(f"發現 {len(unknown_chipsets)} 個未知 chipset，呼叫 LLM 對應")
        new_mappings = llm_map_chipsets(unknown_chipsets, ul_gpu_names)
        # 合併並儲存
        mapping.update(new_mappings)
        _save_mapping(mapping)
        logger.info(f"Mapping 更新完成，新增 {len(new_mappings)} 個對應")
    else:
        logger.info("所有 chipset 已在 Mapping 中，跳過 LLM 呼叫")

    # Step 3：清洗 + CP 計算
    logger.info("Step 3：清洗資料並計算 CP 值...")
    df = clean_and_calculate_cp(coolpc_data, mapping, ul_df)

    if df.empty:
        logger.error("清洗後資料為空，ETL 中止")
        return {"status": "error", "reason": "清洗後資料為空", "date": today}

    df["date"] = today

    # 確保欄位順序
    df = df[["date", "chipset", "product", "price", "pure_chipset", "score", "CP"]]

    # Step 4：寫入 DB（使用 transaction）
    logger.info("Step 4：寫入 filtered_df.db...")
    conn = _get_gpu_db_conn()
    try:
        with conn:
            # 若 force，先刪除今天的舊資料
            if force:
                conn.execute("DELETE FROM filtered_df WHERE date = ?", [today])

            df.to_sql(
                "filtered_df",
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )
        logger.info(f"成功寫入 {len(df)} 筆資料，日期：{today}")
        return {
            "status": "success",
            "date": today,
            "count": len(df),
            "message": f"成功更新 {len(df)} 筆顯示卡資料（{today}）",
        }
    except Exception as e:
        logger.error(f"寫入 DB 失敗：{e}")
        return {"status": "error", "reason": str(e), "date": today}
    finally:
        conn.close()
