# GPU Recommendation Assistant

> 輸入預算或目標顯卡型號，系統會用最新 CoolPC 價格與 UL Benchmark 跑分，推薦同價位 CP 值最高的顯卡。

![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)
![Django](https://img.shields.io/badge/Django-6.0-green?logo=django)
![LLM](https://img.shields.io/badge/LLM-Groq-orange)
![SQLite](https://img.shields.io/badge/DB-SQLite-lightgrey?logo=sqlite)

---

## Features

- 預算推薦：依預算找出 CP 值最高的 Top 3 顯卡
- 目標顯卡比較：顯示目標卡與同價位替代方案
- 一鍵更新資料庫：ETL 抓取最新價格與跑分
- 自動 GPU 名稱對照：LLM 將 CoolPC chipset 對應到 UL 標準名稱

---

## Tech Stack

- Backend: Django 6
- LLM: Groq API (`llama-3.1-8b-instant`，可在 env 覆蓋)
- ETL Crawler: `requests + BeautifulSoup4`
- Data processing: Pandas
- Database: SQLite (`db.sqlite3`, `filtered_df.db`)
- Serving: Gunicorn + WhiteNoise

---

## Quick Start (Local)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables (`.env`)

```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_ORIGINS=http://localhost,http://127.0.0.1

GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.1-8b-instant
```

### 3. Migrate DB

```bash
python manage.py migrate
```

### 4. Run server

```bash
python manage.py runserver 8000
```

Open: `http://127.0.0.1:8000`

---

## ETL Flow

`chat/etl.py` 會執行：

1. 從 CoolPC 抓顯示卡品項（`requests + BeautifulSoup`）
2. 從 UL Benchmark 抓 GPU 分數（`requests + BeautifulSoup`）
3. 用 Groq 進行未知 chipset mapping
4. 清洗資料並計算 `CP = score / price`
5. 寫入 `filtered_df.db`

> 同一天預設只更新一次；可用 `force=True` 強制更新。

---

## API Endpoints

- `GET /`：聊天頁
- `POST /api/chat`：送訊息取得推薦
- `POST /api/update-db`：觸發 ETL 更新
- `GET /api/db-meta`：查資料庫最新日期與筆數

---

## Render Deployment

### Render Web Service settings

- Runtime: `Python 3`
- Build Command: `bash build.sh`
- Start Command:

```bash
gunicorn gpu_recommendation.wsgi:application --bind 0.0.0.0:$PORT
```

### Required Render env vars

```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=gpu-recommendation.onrender.com
DJANGO_CSRF_ORIGINS=https://gpu-recommendation.onrender.com

GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.1-8b-instant
```

### Important notes

- `DJANGO_ALLOWED_HOSTS` 不要加 `https://`
- `DJANGO_CSRF_ORIGINS` 要加 `https://`
- 目前是 SQLite，本地檔案型資料庫在 Render 無持久磁碟時會隨重建遺失

---

## Project Structure

```text
gpu-recommendation/
├── gpu_recommendation/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── chat/
│   ├── etl.py
│   ├── llm_client.py
│   ├── skills.py
│   ├── views.py
│   └── urls.py
├── templates/
├── static/
├── tests/
├── build.sh
├── requirements.txt
├── gpu_mapping_checklist.json
└── filtered_df.db
```

---

## Data Sources

- CoolPC: https://www.coolpc.com.tw/evaluate.php
- UL Benchmark: https://benchmarks.ul.com/compare/best-gpus

---

## License

MIT
