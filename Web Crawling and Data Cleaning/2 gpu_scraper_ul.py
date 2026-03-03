import sqlite3
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# 初始化 SQLite 資料庫
conn = sqlite3.connect("gpus.db")
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS gpus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        score INTEGER NOT NULL
    )
"""
)
conn.commit()

# 設定 headless 模式的 Chrome
options = Options()
# options.add_argument("--headless")
options.add_argument("--disable-gpu")
driver = webdriver.Chrome(options=options)

# 開啟目標網頁
url = "https://benchmarks.ul.com/compare/best-gpus?amount=0&sortBy=SCORE&reverseOrder=true&types=DESKTOP&minRating=0"
driver.get(url)

# 等待 JS 載入完成
time.sleep(5)

# 取得所有 GPU 表格列
rows = driver.find_elements(
    By.XPATH, "/html/body/div[2]/main/div/div[3]/div/div[6]/div/div/table/tbody/tr"
)

print(f"共找到 {len(rows)} 筆顯卡資料")

for index, row in enumerate(rows, start=1):
    try:
        name_xpath = f"/html/body/div[2]/main/div/div[3]/div/div[6]/div/div/table/tbody/tr[{index}]/td[2]/a"
        score_xpath = f"/html/body/div[2]/main/div/div[3]/div/div[6]/div/div/table/tbody/tr[{index}]/td[4]/div/div/span"

        name_element = driver.find_element(By.XPATH, name_xpath)
        score_element = driver.find_element(By.XPATH, score_xpath)

        gpu_name = name_element.text.strip()
        gpu_score = int(score_element.text.strip().replace(",", ""))

        print(f"{index}: {gpu_name} - {gpu_score}")

        # 插入資料到資料庫
        cursor.execute(
            "INSERT INTO gpus (name, score) VALUES (?, ?)", (gpu_name, gpu_score)
        )
        conn.commit()
    except Exception as e:
        print(f"第 {index} 筆資料發生錯誤: {e}")
        continue

driver.quit()
conn.close()
