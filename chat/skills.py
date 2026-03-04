"""
Skill 函式：後端受控查詢
所有 DB 操作皆透過此模組，LLM 不得生成任意 SQL。
"""
import logging
import sqlite3

from django.conf import settings

logger = logging.getLogger(__name__)

FILTER_KEYWORDS = [
    "贈", "抽", "送", "加購", "登錄", "活動", "限量", "現省",
    "現折", "現賺", "再加", "加送", "加價購", "[合購]", "[紅包",
]

BLACKLIST_CHIPSETS = [
    "NVIDIA Quadro 專業繪圖卡",
    "NVIDIA Quadro 專業繪圖卡 (歡迎議價)",
    "NVIDIA 專業繪圖卡",
    "AMD 工作站繪圖卡",
]


def _get_connection() -> sqlite3.Connection:
    db_path = str(settings.GPU_DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _db_ready() -> bool:
    """檢查 filtered_df 資料表是否存在（初始化用）"""
    try:
        conn = _get_connection()
        try:
            conn.execute("SELECT 1 FROM filtered_df LIMIT 1")
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()
    except Exception:
        return False


def skill_get_gpu_recommendations(
    budget_twd: int | None,
    target_gpu: str | None,
    price_window_pct: float = 0.10,
    top_k: int = 3,
) -> dict:
    """
    查詢最新日期資料，回傳 CP 值最高的 Top K 顯示卡。
    支援預算模式和目標顯卡比較模式。
    候選不足時自動放寬 ±5%，最大到 ±30%。
    """
    if budget_twd is None and target_gpu is None:
        return {"error": "請提供預算或目標顯卡名稱"}

    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # 取得最新日期
        try:
            cursor.execute("SELECT MAX(date) FROM filtered_df")
        except sqlite3.OperationalError:
            return {"error": "資料庫尚未建立，請先點擊右上角「更新資料庫」按鈕"}
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        if not latest_date:
            return {"error": "資料庫目前沒有資料，請先更新資料庫"}

        # 決定基準價格
        base_price = budget_twd
        target_gpu_info = None       # 目標卡代表資訊
        exclude_pure_chipset = None  # 比較模式：排除目標卡整個型號

        if target_gpu is not None:
            # 目標顯卡模式：找到目標卡的最優代表（CP 最高那筆）
            candidates = skill_search_gpu_candidates(target_gpu)
            if not candidates:
                return {"error": f"找不到顯示卡：{target_gpu}，請嘗試其他關鍵字"}
            # 取 CP 最高的那筆作為代表
            best_match = candidates[0]
            base_price = best_match["price"]
            target_gpu_info = best_match
            # 排除整個 pure_chipset（避免同型號不同品牌的卡佔滿替代方案）
            exclude_pure_chipset = best_match.get("pure_chipset")

        if base_price is None:
            return {"error": "無法確定基準價格"}

        # 逐步放寬價格區間
        window_pct = price_window_pct
        results = []
        while window_pct <= 0.30:
            low = int(base_price * (1 - window_pct))
            high = int(base_price * (1 + window_pct))

            sql = """
                SELECT date, chipset, product, price, pure_chipset, score, CP
                FROM filtered_df
                WHERE date = ?
                  AND price BETWEEN ? AND ?
            """
            params = [latest_date, low, high]

            if exclude_pure_chipset:
                sql += " AND pure_chipset != ?"
                params.append(exclude_pure_chipset)

            sql += " ORDER BY CP DESC LIMIT ?"
            params.append(top_k)

            cursor.execute(sql, params)
            rows = cursor.fetchall()
            results = [dict(r) for r in rows]

            if len(results) >= top_k:
                break
            window_pct += 0.05

        return {
            "recommendations": results,
            "target_gpu_info": target_gpu_info,   # 比較模式：目標卡代表資訊
            "base_price": base_price,
            "window_used_pct": round(window_pct * 100),
            "latest_date": latest_date,
            "count": len(results),
        }
    finally:
        conn.close()



def skill_search_gpu_candidates(query: str) -> list:
    """搜尋 DB 內有的顯示卡，用關鍵字比對 chipset / pure_chipset / product"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(date) FROM filtered_df")
        except sqlite3.OperationalError:
            return []
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        if not latest_date:
            return []

        like_query = f"%{query}%"
        cursor.execute(
            """
            SELECT date, chipset, product, price, pure_chipset, score, CP
            FROM filtered_df
            WHERE date = ?
              AND (chipset LIKE ? OR pure_chipset LIKE ? OR product LIKE ?)
            ORDER BY CP DESC
            LIMIT 10
            """,
            [latest_date, like_query, like_query, like_query],
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def skill_get_db_meta() -> dict:
    """回傳最後更新日期、來源、最新 date 中的顯示卡筆數"""
    try:
        conn = _get_connection()
    except Exception:
        return {"latest_date": None, "count": 0, "source": "CoolPC + UL Benchmark", "db_ready": False}
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(date) FROM filtered_df")
        except sqlite3.OperationalError:
            return {"latest_date": None, "count": 0, "source": "CoolPC + UL Benchmark", "db_ready": False}
        row = cursor.fetchone()
        latest_date = row[0] if row else None

        count = 0
        if latest_date:
            cursor.execute(
                "SELECT COUNT(*) FROM filtered_df WHERE date = ?", [latest_date]
            )
            count = cursor.fetchone()[0]

        return {
            "latest_date": latest_date,
            "count": count,
            "source": "CoolPC + UL Benchmark",
            "db_ready": latest_date is not None,
        }
    finally:
        conn.close()


def skill_update_database(source: str = "coolpc_live_and_ul", force: bool = False) -> dict:
    """觸發 ETL 更新（呼叫 chat/etl.py run_etl()）"""
    from chat.etl import run_etl
    return run_etl(force=force)
