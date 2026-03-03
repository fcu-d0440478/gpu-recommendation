import requests
import sqlite3
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import re
import time

# Step 1: 初始化 SQLite 資料庫
conn = sqlite3.connect("vga.db")
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS vga (
        date TEXT,
        chipset TEXT,
        product TEXT,
        price INTEGER,
        UNIQUE(date, chipset, product)
    )
"""
)
conn.commit()

# 讀取已存在的日期
existing_dates = set(row[0] for row in cursor.execute("SELECT DISTINCT date FROM vga"))

# Step 2: 查詢 Wayback 快照列表
cdx_url = "https://web.archive.org/cdx/search/cdx"
params = {
    "url": "www.coolpc.com.tw/evaluate.php",
    "from": "20200101",
    "output": "json",
    "fl": "timestamp,original",
    "collapse": "timestamp:8",
}
response = requests.get(cdx_url, params=params)
snapshots = response.json()[1:]  # 忽略 header

# Step 3: 設定 Selenium Headless 模式
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--log-level=3")
driver = webdriver.Chrome(options=chrome_options)

# Step 4: 爬取每一筆快照
for snapshot in snapshots:
    timestamp = snapshot[0]
    date = timestamp[:8]

    if date in existing_dates:
        print(f"⏩ 已存在：{date}，略過")
        continue

    print(f"📅 正在處理 {date} ...")
    url = f"https://web.archive.org/web/{timestamp}/https://www.coolpc.com.tw/evaluate.php"

    try:
        driver.get(url)
        time.sleep(5)

        vga_td = driver.find_element(
            By.XPATH, '//td[contains(text(),"顯示卡VGA")]/following-sibling::td[1]'
        )
        optgroups = vga_td.find_elements(By.XPATH, ".//optgroup")

        for optgroup in optgroups:
            chipset = optgroup.get_attribute("label").strip()
            options = optgroup.find_elements(By.TAG_NAME, "option")

            for option in options:
                text = " ".join(option.text.split())
                match = re.search(r"(.+?),?\s*\$([\d,]+)", text)
                if match:
                    product = match.group(1).strip()
                    price = int(match.group(2).replace(",", ""))
                    cursor.execute(
                        "INSERT OR IGNORE INTO vga (date, chipset, product, price) VALUES (?, ?, ?, ?)",
                        (date, chipset, product, price),
                    )
        conn.commit()
        existing_dates.add(date)

    except Exception as e:
        print(f"⚠️  跳過 {date}（錯誤：{e}）")
        continue

# 關閉
driver.quit()
conn.close()
print("✅ 所有快照處理完畢，資料寫入 vga.db 完成")
