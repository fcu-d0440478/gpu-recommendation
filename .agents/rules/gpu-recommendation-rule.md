---
trigger: always_on
---

# GPU 推薦專案 — 專案規範 (Rules)

> 版本：2.0 ｜ 更新日期：2026-03-03  
> **本文件為最新版規範，舊版一切描述以本文件為準。**

---

## 0. 專案目標

使用者透過聊天 UI 詢問顯示卡推薦（依預算或指定顯卡），系統從 SQLite 資料庫中找出「最新日期、價格相近、CP 值最高」的顯示卡，透過 Ollama（qwen3:4b）生成繁體中文回覆，並說明選擇理由。

---

## 1. 技術選型（固定）

| 層次       | 技術                              |
|------------|-----------------------------------|
| Backend    | Django (Python)                   |
| DB         | SQLite (`filtered_df.db`)         |
| LLM        | Ollama，**模型固定為 `qwen3:4b`** |
| Frontend   | Django Template + HTMX            |
| 爬蟲 / ETL | Selenium + Pandas（整合自 `Web Crawling and Data Cleaning/`） |

---

## 2. 資料庫規格

### 2.1 資料庫與資料表

- 檔案名稱：`filtered_df.db`
- 資料表名稱：`filtered_df`

```sql
CREATE TABLE "filtered_df" (
    "date"         TEXT,      -- 格式 YYYYMMDD，如 20251118
    "chipset"      TEXT,      -- CoolPC 上的原始晶片組分類
    "product"      TEXT,      -- 完整商品名稱
    "price"        INTEGER,   -- 台幣售價
    "pure_chipset" TEXT,      -- 標準化晶片名稱（對應 UL 跑分）
    "score"        INTEGER,   -- UL TimeSpy 跑分
    "CP"           REAL       -- CP 值 = score / price
)
```

### 2.2 範例資料

```
date        chipset                  product                                                  price   pure_chipset            score   CP
20251118    AMD Radeon RX9060XT-8G   [雙11任搭]藍寶石 脈動 PULSE RX9060XT GAMING OC 8GB      8888    AMD Radeon RX 9060 XT   3719    0.4184
20251118    AMD Radeon RX9060XT-8G   Acer Nitro RX9060XT OC 8GB(3320MHz/27cm/雙風扇/三年保固) 9990    AMD Radeon RX 9060 XT   3719    0.3723
```

### 2.3 僅使用最新日期資料（重要規則）

- 每次查詢都必須先取得 DB 中最大的 `date` 值：
  ```sql
  SELECT MAX(date) FROM filtered_df;
  ```
- 所有查詢結果必須加上 `WHERE date = (SELECT MAX(date) FROM filtered_df)` 條件。
- 絕對不可將不同日期的資料混合比較或回傳。

---

## 3. ETL / 資料更新流程

### 3.1 來源整合（整合自 `Web Crawling and Data Cleaning/`）

> **架構原則**
> - 爬蟲部分：**直接參照**並整合 `Web Crawling and Data Cleaning/` 內的現有腳本邏輯
> - Mapping 部分：**不再使用舊腳本**，一律改由 LLM（qwen3:4b）自動對應（規則見 3.1.3）

**ETL 整體流程（在 `chat/etl.py` 的 `run_etl()` 執行）：**

| 階段 | 與 Web Crawling and Data Cleaning 的關係 | 說明 |
|------|------|------|
| Step 1：爬取 CoolPC | **參照** `1 wayback_vga_tracker.py` 的爬取邏輯 | 爬取 evaluate.php 的 VGA optgroup，取得 chipset、product、price |
| Step 2：爬取 UL 跑分 | **參照** `2 gpu_scraper_ul.py` 的爬取邏輯 | 爬取 UL Benchmark，取得 GPU 名稱與 score |
| Step 3：名稱對應 | **不使用舊腳本**，改由 LLM 全自動對應 | 見 3.1.3 |
| Step 4：清洗 + CP 計算 | **參照** `4 pre_process_data.ipynb` 的清洗邏輯 | Pandas 邏輯：過濾無效詞、計算 CP、剔除無分數資料 |

- ETL 入口為 `chat/etl.py` 中的 `run_etl()` 函式
- 清洗規則（參照 `4 pre_process_data.ipynb`）：
  - 過濾含有「贈、抽、送、加購、登錄、活動、限量、現省、現折、現賺、再加、加送、加價購、[合購]、[紅包」等關鍵字的 product
  - 過濾工作站繪圖卡等不適用的 chipset 類別
  - 僅保留 `pure_chipset` 與 `score` 均有值的資料

### 3.1.1 分數來源（UL Benchmark）

- **來源 URL**：[https://benchmarks.ul.com/compare/best-gpus?amount=0&sortBy=SCORE&reverseOrder=true&types=DESKTOP&minRating=0](https://benchmarks.ul.com/compare/best-gpus?amount=0&sortBy=SCORE&reverseOrder=true&types=DESKTOP&minRating=0)
- 取得欄位：GPU 名稱（`name`）、UL TimeSpy 跑分（`score`）
- 爬取腳本：`Web Crawling and Data Cleaning/2 gpu_scraper_ul.py`（Selenium headless）
- 同型號有多筆時，取最高分並去重（`drop_duplicates(subset='name', keep='first')`）

### 3.1.2 名稱對應問題（Mapping）

**背景說明：**
原價屋（CoolPC）的顯卡分類名稱（`chipset`）與 UL Benchmark 的標準名稱（`name`）格式不一致，無法直接比對：

| 來源 | 範例名稱 |
|------|----------|
| 原價屋 chipset | `AMD Radeon RX9060XT-8G` |
| UL Benchmark | `AMD Radeon RX 9060 XT` |
| 原價屋 chipset | `NVIDIA RTX4070-12G` |
| UL Benchmark | `NVIDIA GeForce RTX 4070` |

因此需要一個由 **LLM 自動維護**的 **Mapping 對照表**，將兩邊的名稱橋接起來。不需要任何人工介入。

### 3.1.3 Mapping 建立與維護流程（LLM 全自動）

**不需要人工介入**。整個 Mapping 流程由後端在 ETL 執行時自動完成：

```
步驟 1：爬取資料
  ├── CoolPC chipset 清單  ← 1 wayback_vga_tracker.py
  └── UL GPU 名稱清單     ← 2 gpu_scraper_ul.py

步驟 2：LLM 自動 Mapping（chat/etl.py 內部觸發）
  ├── 找出尚未有對應的 chipset（不在現有 mapping JSON 內）
  ├── 呼叫 Ollama（qwen3:4b）進行批次對應
  └── 將回覆結果合併寫入 3 gpu_mapping_checklist.json

步驟 3：Pandas 清洗 + CP 計算
  └── 使用更新後的 mapping JSON 進行 pure_chipset 轉換
```

**Mapping JSON 結構（`3 gpu_mapping_checklist.json`）：**
```json
{
  "AMD Radeon RX9060XT-8G": "AMD Radeon RX 9060 XT",
  "NVIDIA RTX4090": "NVIDIA GeForce RTX 4090",
  "NVIDIA Quadro 專業繪圖卡": null,
  "AMD 工作站繪圖卡": null
}
```
- value 為 `null` 表示此 chipset 不在推薦範圍（配件、工作站卡等）
- JSON 作為**快取層**：已對應過的 chipset 不重複呼叫 LLM

**對應到 `filtered_df.db` 欄位的關係：**
```
CoolPC chipset  →（mapping JSON / LLM 自動產生）→  pure_chipset（UL 標準名稱）→  score
```

### 3.1.4 LLM 自動 Mapping 規則

#### Prompt 設計要求

ETL 執行時，對**未知 chipset** 批次呼叫 Ollama：

```
System Prompt:
你是 GPU 型號對應專家。請將 CoolPC 原價屋的顯卡分類名稱（chipset）
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
4. 只輸出 JSON 物件，不要任何其他文字

標準 GPU 型號列表：
{ul_gpu_names_json}

待對應的 chipset 列表：
{unknown_chipsets_json}

輸出格式：
{"chipset名稱": "標準GPU名稱或null"}
```

#### 執行時機與快取策略

| 情況 | 行為 |
|------|------|
| chipset 已在 JSON 中 | 直接使用快取，不呼叫 LLM |
| chipset 不在 JSON 中 | 批次呼叫 LLM 進行對應 |
| LLM 回覆的名稱不在 UL 清單中 | 記錄為 `null`，人工日後補充 |
| LLM 回覆格式錯誤 | 捕捉例外、跳過該批次、記錄 log |

#### 寫回規則

- LLM 對應完成後，**立即合併寫入** `3 gpu_mapping_checklist.json`（不覆蓋已有 key）
- 寫入前驗證：LLM 回傳的 value 必須存在於 UL GPU 名稱清單中，否則設為 `null`
- **Mapping JSON 是唯一的真實來源**，不可在程式碼中硬編碼對應關係

### 3.2 寫入規則

- ETL 執行完畢後寫入 `filtered_df.db` 的 `filtered_df` 表格
- 每次 ETL 使用當天日期（`YYYYMMDD` 格式）作為 `date` 欄位
- 使用 SQLite transaction，失敗時 rollback
- 寫入前檢查是否已有相同 date 的資料，若有且非 `force=True` 則跳過

### 3.3 觸發條件

- 只有使用者**明確要求**（如「更新資料庫」「刷新資料」「同步最新價格」）才觸發
- 後端節流：同一天內不重複更新（除非 `force=True`）

---

## 4. 核心商業邏輯：CP 值推薦

### 4.1 CP 值定義

```
CP = score / price   （score = UL TimeSpy 跑分，price = 台幣售價）
```

CP 值越高，代表相同預算能獲得更好的效能。

### 4.2 兩種查詢模式

**模式 A：預算模式**
```
WHERE date = MAX(date)
  AND price BETWEEN budget * (1 - window_pct) AND budget * (1 + window_pct)
ORDER BY CP DESC
LIMIT top_k
```

**模式 B：目標顯卡模式**
- 先用關鍵字搜尋找到目標卡的 price，再套用上述邏輯（排除目標卡本身）

### 4.3 預設參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `price_window_pct` | 0.10 | ±10% 價格浮動 |
| `top_k` | 3 | 推薦數量 |

### 4.4 候選不足時的放寬邏輯

若候選數 < top_k，每次放寬 5%（10% → 15% → 20%），回覆中須說明已放寬範圍。

---

## 5. Skill 函式規範（後端受控查詢）

所有資料查詢皆只能透過以下 skill 函式進行，**LLM 不得生成任意 SQL**：

```python
# chat/skills.py

def skill_get_gpu_recommendations(
    budget_twd: int | None,
    target_gpu: str | None,
    price_window_pct: float = 0.10,
    top_k: int = 3
) -> dict:
    """
    查詢最新日期資料，回傳 CP 值最高的 Top K 顯示卡。
    必須加 WHERE date = (SELECT MAX(date) FROM filtered_df)
    """

def skill_search_gpu_candidates(query: str) -> list:
    """搜尋 DB 內有的卡，用關鍵字比對 chipset / pure_chipset / product"""

def skill_get_db_meta() -> dict:
    """回傳最後更新日期、來源、最新 date 中的顯示卡筆數"""

def skill_update_database(source: str = "coolpc_live_and_ul", force: bool = False) -> dict:
    """觸發 ETL 更新（呼叫 chat/etl.py run_etl()）"""
```

> **規則**：所有 skill 查詢 `filtered_df` 時，必須加上最新日期限制，確保只操作最新資料。

---

## 6. LLM（Ollama qwen3:4b）使用規範

### 6.1 模型設定

- **模型**：`qwen3:4b`（固定，不可更換）
- **API URL**：`http://localhost:11434/api/generate`
- **stream**：`False`（等待完整回覆）
- **timeout**：60 秒

### 6.2 回覆時的強制要求

1. **只能使用 DB 中實際存在的資料**，不得虛構顯示卡名稱、價格或分數
2. 回覆必須包含：
   - 推薦結論（Top 1 是什麼，為什麼）
   - Top 3 清單（名稱、價格、分數、CP 值、與預算差距）
   - 對每張卡說明選擇理由（CP 值優勢、價格說明等）
3. 若資料不足，說明缺少什麼，並建議下一步
4. 全程使用**繁體中文**，語氣親切專業

### 6.3 System Prompt 核心內容

```
你是一個專業的顯示卡推薦助手。你只使用系統提供的資料庫查詢結果，絕對不可虛構或猜測任何顯示卡的規格、價格或分數。

回覆時必須：
1. 說明為何推薦這幾張卡（CP 值計算、與預算差距等）
2. 列出 Top 3 推薦清單（表格或條列皆可）
3. 每張卡給出 1~2 句推薦理由
4. 全程使用繁體中文
```

### 6.4 未提供預算時的處理

若使用者沒提供預算也沒提目標卡，LLM 必須反問：
> 「請問您的預算大約是多少？或者有想比較的目標顯卡型號嗎？」

---

## 7. API 設計

| Method | URL | 說明 |
|--------|-----|------|
| POST | `/api/chat` | 接收訊息，呼叫 skill + Ollama，回傳推薦 |
| POST | `/api/update-db` | 觸發 ETL 更新（含節流保護） |
| GET  | `/api/db-meta` | 回傳最後更新時間、來源、顯示卡數量 |

### Request / Response 格式

```
POST /api/chat
Body: { "message": "預算15000推薦顯卡" }
Response: {
  "assistant_message": "...",
  "recommendations": [
    {
      "name": "...",
      "price": 14990,
      "score": 12345,
      "cp": 0.823,
      "price_diff_pct": "+0.1%",
      "reason": "CP 值在同價位中最高..."
    }
  ],
  "base_price": 15000,
  "window_used_pct": 10,
  "latest_date": "20251118"
}
```

---

## 8. 前端 UI 規範

### 8.1 主要區塊

1. **Chat 面板**：輸入框 + 送出按鈕 + 對話紀錄（使用 HTMX 非同步）
2. **推薦結果卡片**：每張顯示卡名稱、價格、分數、CP 值、價差、推薦理由
3. **資料狀態列**：顯示最後更新時間 + 最新資料日期 + [更新資料庫] 按鈕

### 8.2 互動規則

- 送出訊息後顯示「正在分析...」Spinner
- 更新 DB 按鈕按下後：disabled + loading，完成後 Toast 通知結果
- 推薦卡片要顯示 `data-date` 屬性，表明資料來源日期

---

## 9. 資料真實性規則（最重要）

以下行為**嚴格禁止**：

- ❌ LLM 回覆中虛構不存在於 DB 的顯示卡名稱
- ❌ LLM 虛構任何價格、分數或 CP 值
- ❌ 混合不同日期的資料進行比較
- ❌ 直接讓 LLM 生成 SQL 執行於 DB
- ❌ 回覆使用非台幣的價格單位

以下行為**強制要求**：

- ✅ 所有查詢加上 `WHERE date = MAX(date)` 限制
- ✅ 回覆數據來源皆可在 DB 中查證
- ✅ 若 DB 中沒有符合條件的資料，誠實告知使用者

---

## 10. 測試規範

- **單元測試**（`pytest`）：
  - CP 計算正確性
  - 最新日期篩選邏輯
  - 價格區間放寬邏輯（10% → 15% → 20%）
- **整合測試**：
  - `/api/chat` 在固定 DB 下可重現輸出
  - `/api/update-db` 成功 / 失敗格式正確
  - 回傳資料的 `date` 欄位必須為 DB 中最大日期

---

## 11. 完成定義（Definition of Done）

- [ ] 使用者輸入預算或目標卡 → 穩定回傳最新日期的 Top 3 推薦
- [ ] 回覆說明 CP 值優勢與選擇理由
- [ ] UI 呈現聊天回覆 + 推薦卡片 + 最後更新時間
- [ ] 更新 DB 按鈕可正確觸發 ETL（整合 Web Crawling and Data Cleaning 腳本）
- [ ] 測試通過
- [ ] 所有回覆資料可在 `filtered_df.db` 中查證，無虛構資料
