"""
單元測試：Skill 函式
"""
import os
import sqlite3
import tempfile
from unittest.mock import patch

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gpu_recommendation.settings')

import pytest


@pytest.fixture
def sample_db(tmp_path):
    """建立含測試資料的臨時資料庫"""
    db_path = tmp_path / "test_filtered_df.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE filtered_df (
            date TEXT, chipset TEXT, product TEXT, price INTEGER,
            pure_chipset TEXT, score INTEGER, CP REAL
        )
    """)
    # 插入最新日期資料
    conn.executemany(
        "INSERT INTO filtered_df VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("20251118", "AMD Radeon RX7700XT-12G", "Sapphire RX 7700 XT", 12000, "AMD Radeon RX 7700 XT", 12000, 1.0),
            ("20251118", "NVIDIA RTX4070-12G", "ASUS RTX 4070", 14000, "NVIDIA GeForce RTX 4070", 11000, 0.786),
            ("20251118", "AMD Radeon RX7800XT-16G", "PowerColor RX 7800 XT", 16000, "AMD Radeon RX 7800 XT", 15000, 0.9375),
            # 舊日期資料（不應出現在查詢結果）
            ("20251001", "AMD Radeon RX7700XT-12G", "Old Card", 9999, "AMD Radeon RX 7700 XT", 12000, 1.2),
        ]
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def patch_db(sample_db, settings):
    """將 GPU_DB_PATH 指向測試資料庫"""
    settings.GPU_DB_PATH = sample_db


# ---- 測試：最新日期過濾 ----

def test_only_latest_date_returned(sample_db, settings):
    """確認查詢結果只包含最新日期"""
    from chat.skills import skill_get_gpu_recommendations
    result = skill_get_gpu_recommendations(budget_twd=14000, target_gpu=None)
    recs = result.get("recommendations", [])
    for rec in recs:
        assert rec["date"] == "20251118", f"發現非最新日期資料：{rec['date']}"


def test_latest_date_meta(sample_db, settings):
    """確認 meta 回傳最新日期"""
    from chat.skills import skill_get_db_meta
    meta = skill_get_db_meta()
    assert meta["latest_date"] == "20251118"
    assert meta["count"] == 3  # 最新日期有 3 筆


# ---- 測試：CP 計算正確性 ----

def test_cp_calculation(sample_db, settings):
    """查詢結果應依 CP 降序排列"""
    from chat.skills import skill_get_gpu_recommendations
    result = skill_get_gpu_recommendations(budget_twd=15000, target_gpu=None, price_window_pct=0.30)
    recs = result.get("recommendations", [])
    assert len(recs) > 0
    # 驗證排序
    cps = [r["CP"] for r in recs]
    assert cps == sorted(cps, reverse=True), "結果應依 CP 降序排列"


def test_cp_value_correctness(sample_db, settings):
    """驗證 CP = score / price"""
    from chat.skills import skill_search_gpu_candidates
    results = skill_search_gpu_candidates("RX 7700 XT")
    assert len(results) > 0
    rec = results[0]
    expected_cp = rec["score"] / rec["price"]
    assert abs(rec["CP"] - expected_cp) < 0.001


# ---- 測試：價格區間放寬邏輯 ----

def test_price_window_10pct(sample_db, settings):
    """預算 ±10% 內應能找到資料"""
    from chat.skills import skill_get_gpu_recommendations
    result = skill_get_gpu_recommendations(budget_twd=12000, target_gpu=None, price_window_pct=0.10)
    recs = result.get("recommendations", [])
    window = result.get("window_used_pct", 10) / 100
    for rec in recs:
        assert 12000 * (1 - window) <= rec["price"] <= 12000 * (1 + window)


def test_price_window_relaxation(sample_db, settings):
    """候選不足時應自動放寬價格區間"""
    from chat.skills import skill_get_gpu_recommendations
    # 預算 5000，±10% 內可能沒有資料，應放寬
    result = skill_get_gpu_recommendations(budget_twd=5000, target_gpu=None, price_window_pct=0.10, top_k=3)
    # 此時因資料庫沒有 5000 元的卡，推薦可能為空（但不應崩潰）
    assert "recommendations" in result


def test_window_relaxation_returns_more(sample_db, settings):
    """放寬後應取得更多結果"""
    from chat.skills import skill_get_gpu_recommendations
    # 很窄的區間
    result_tight = skill_get_gpu_recommendations(budget_twd=14000, target_gpu=None, price_window_pct=0.01, top_k=3)
    result_wide = skill_get_gpu_recommendations(budget_twd=14000, target_gpu=None, price_window_pct=0.30, top_k=3)
    assert result_wide["count"] >= result_tight["count"]


# ---- 測試：搜尋功能 ----

def test_search_by_keyword(sample_db, settings):
    """關鍵字搜尋應能找到對應顯示卡"""
    from chat.skills import skill_search_gpu_candidates
    results = skill_search_gpu_candidates("RTX 4070")
    assert len(results) > 0
    assert any("4070" in r.get("pure_chipset", "") or "4070" in r.get("product", "") for r in results)


def test_search_no_result(sample_db, settings):
    """不存在的型號應回傳空清單"""
    from chat.skills import skill_search_gpu_candidates
    results = skill_search_gpu_candidates("RTX 9999")
    assert results == []
