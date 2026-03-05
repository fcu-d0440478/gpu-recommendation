# 🎮 GPU 推薦助手

> 輸入預算或目標顯卡型號，AI 從最新原價屋價格資料中，找出 CP 值最高的 Top 3 顯示卡推薦。

![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)
![Django](https://img.shields.io/badge/Django-6.0-green?logo=django)
![Ollama](https://img.shields.io/badge/LLM-qwen3:4b-purple)
![SQLite](https://img.shields.io/badge/DB-SQLite-lightgrey?logo=sqlite)

---

## 📸 功能預覽

| 預算推薦模式 | 目標顯卡比較模式 |
|---|---|
| 輸入「預算 15000」，列出同價位 CP 值最高的 3 張卡 | 輸入「比較 RTX 5060」，顯示目標卡 vs 同價位替代方案 |

---

## ⚡ 快速啟動

### 前置需求

| 工具 | 版本 | 說明 |
|------|------|------|
| Python | 3.10+ | 後端語言 |
| Ollama | 最新版 | 本地 LLM 服務 |
| Chrome + ChromeDriver | 配對版本 | ETL 爬蟲用（可選，已有資料可跳過） |

### 1. 安裝 Ollama 並下載模型

```bash
# 安裝 Ollama（官網：https://ollama.com）
# 下載推薦模型
ollama pull qwen3:4b

# 啟動 Ollama 服務
ollama serve
```

### 2. 安裝 Python 套件

```bash
pip install -r requirements.txt
```

### 3. 初始化 Django 資料庫

```bash
python manage.py migrate
```

### 4. 啟動開發伺服器

```bash
python manage.py runserver 8000
```

### 5. 開啟瀏覽器

```
http://127.0.0.1:8000
```

---

## 🖥️ 使用方式

### 預算推薦

在對話框輸入預算，系統自動查詢同價位 CP 值最高的 3 張顯示卡：

```
預算 15000 元推薦顯卡
15000
budget 15000
```

### 目標顯卡比較

輸入想比較的顯卡型號，系統顯示該卡與同價位替代方案的比較：

```
幫我比較 RTX 5060
比較 RX 9060 XT 同價位選擇
RTX 5070 有沒有更划算的替代品
```

### 更新資料庫

點擊右上角「**更新資料庫**」按鈕，觸發 ETL 爬取最新原價屋與 UL Benchmark 資料。

> ⚠️ 更新需要 ChromeDriver，且同一天只更新一次（除非強制更新）。

---

## 🏗️ 專案架構

```
gpu-recommendation/
├── gpu_recommendation/          # Django 專案設定
│   ├── settings.py             # 設定（DB 路徑、Ollama URL 等）
│   └── urls.py                 # 根路由
│
├── chat/                        # 核心 App
│   ├── views.py                # API endpoints + 意圖提取
│   ├── skills.py               # DB 查詢封裝（skill 函式）
│   ├── etl.py                  # ETL 全流程
│   ├── ollama_client.py        # Ollama API 封裝
│   └── urls.py                 # chat 路由
│
├── templates/chat/index.html    # 聊天介面
├── static/
│   ├── css/style.css           # 暗色主題設計
│
├── tests/
│   └── test_skills.py          # pytest 單元測試
│
├── gpu_mapping_checklist.json   # GPU 名稱對照快取
├── filtered_df.db               # SQLite 資料庫（GPU 價格 + 跑分）
└── requirements.txt
```

---

## 🔧 運作原理

### 資料流程

```
原價屋 (CoolPC)          UL Benchmark
     │                       │
     ▼                       ▼
  爬取 GPU 列表           爬取跑分資料
  (chipset, product,      (name, score)
   price)                    │
     │                       │
     └──────────┬────────────┘
                ▼
         LLM 自動 Mapping
      (qwen3:4b 批次對應
       CoolPC 名稱 → UL 標準名稱)
                │
                ▼
         Pandas 清洗
      (過濾贈品/促銷字樣,
       計算 CP = score / price)
                │
                ▼
         寫入 filtered_df.db
```

### CP 值計算

```
CP 值 = UL TimeSpy 跑分 / 台幣售價
```

CP 值越高 = 相同預算下效能越好。

### 查詢邏輯

```
使用者輸入
    │
    ▼
意圖提取（規則式）
    ├─ 有預算數字 → 預算模式
    └─ 有 GPU 型號 → 比較模式
         │
         ▼
   skill_get_gpu_recommendations()
    WHERE date = MAX(date)          ← 只用最新資料
    AND price BETWEEN               ← ±10% 價格區間
    ORDER BY CP DESC LIMIT 3       ← 取 CP 前三名
         │
         ▼（若候選不足，自動放寬 ±5%，最大到 ±30%）
         │
         ▼
   Ollama qwen3:4b 生成回覆
    ├─ 預算模式：推薦 Top 3，說明 CP 優勢
    └─ 比較模式：目標卡 vs 替代方案對比分析
```

---

## 🌐 API 端點

| Method | URL | 說明 |
|--------|-----|------|
| `GET`  | `/` | 聊天介面主頁 |
| `POST` | `/api/chat` | 送出訊息，回傳推薦結果 |
| `POST` | `/api/update-db` | 觸發 ETL 更新資料庫 |
| `GET`  | `/api/db-meta` | 查詢資料庫狀態（最新日期、筆數） |

### POST `/api/chat` 範例

**Request:**
```json
{ "message": "預算 15000 元推薦顯卡" }
```

**Response:**
```json
{
  "assistant_message": "根據資料庫查詢，Top 1 推薦為...",
  "recommendations": [
    {
      "product": "藍寶石 PULSE RX 9060 XT 8GB",
      "pure_chipset": "AMD Radeon RX 9060 XT",
      "price": 10990,
      "score": 3719,
      "CP": 0.3384,
      "price_diff_pct": "-8.3%"
    }
  ],
  "base_price": 15000,
  "window_used_pct": 10,
  "latest_date": "20251118"
}
```

---

## 💾 資料庫結構

**資料庫檔案：** `filtered_df.db`  
**資料表：** `filtered_df`

| 欄位 | 類型 | 說明 |
|------|------|------|
| `date` | TEXT | 資料日期（YYYYMMDD） |
| `chipset` | TEXT | 原價屋的晶片組分類名稱 |
| `product` | TEXT | 完整商品名稱 |
| `price` | INTEGER | 台幣售價 |
| `pure_chipset` | TEXT | 標準化 GPU 名稱（對應 UL 跑分） |
| `score` | INTEGER | UL TimeSpy 跑分 |
| `CP` | REAL | CP 值 = score / price |

> ⚠️ 所有查詢都加上 `WHERE date = MAX(date)` 條件，保證只使用最新資料。

---

## 🧪 執行測試

```bash
python -m pytest tests/ -v
```

測試涵蓋：
- 最新日期過濾邏輯
- CP 值計算正確性
- 價格區間放寬邏輯（10% → 15% → 20%）
- 關鍵字搜尋功能

---

## ⚙️ 環境設定

複製 `.env.example` 並修改：

```bash
cp .env.example .env
```

| 設定項 | 預設值 | 說明 |
|--------|--------|------|
| `DJANGO_SECRET_KEY` | （需設定）| Django Secret Key |
| `OLLAMA_API_URL` | `http://localhost:11434/api/generate` | Ollama API 位址 |
| `OLLAMA_MODEL` | `qwen3:4b` | 使用的模型（固定） |
| `OLLAMA_TIMEOUT` | `120` | Ollama 請求逾時（秒） |

---

## 🛠️ 技術選型

| 層次 | 技術 | 說明 |
|------|------|------|
| 後端 | Django 6.0 | Web 框架 |
| 資料庫 | SQLite | GPU 價格與跑分儲存 |
| LLM | Ollama + qwen3:4b | 本地推理，生成繁中推薦回覆 |
| 前端 | Vanilla JS + CSS | 無框架，AJAX 非同步聊天 |
| 爬蟲 | Selenium | 爬取 CoolPC 和 UL Benchmark |
| 資料處理 | Pandas | 清洗與 CP 值計算 |
| 測試 | pytest + pytest-django | 單元測試與整合測試 |

---

## 📋 資料來源

- **原價屋 (CoolPC)**：[https://www.coolpc.com.tw/evaluate.php](https://www.coolpc.com.tw/evaluate.php) — GPU 即時報價
- **UL Benchmark**：[https://benchmarks.ul.com/compare/best-gpus](https://benchmarks.ul.com/compare/best-gpus) — TimeSpy 跑分資料

---

## 📝 License

MIT
