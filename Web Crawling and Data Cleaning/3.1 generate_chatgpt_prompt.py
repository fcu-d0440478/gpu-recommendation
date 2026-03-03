import sqlite3
import json


def generate_chatgpt_prompt():
    """產生可以直接貼到 ChatGPT 的 prompt 檔案"""

    # 連接資料庫
    vga_conn = sqlite3.connect("vga.db")
    gpus_conn = sqlite3.connect("gpus.db")

    # 取得所有唯一的 chipset
    vga_cursor = vga_conn.cursor()
    vga_cursor.execute("SELECT DISTINCT chipset FROM vga ORDER BY chipset")
    chipsets = [row[0] for row in vga_cursor.fetchall()]

    # 取得所有標準 GPU 名稱
    gpus_cursor = gpus_conn.cursor()
    gpus_cursor.execute("SELECT name FROM gpus ORDER BY score DESC")
    gpu_names = [row[0] for row in gpus_cursor.fetchall()]

    print(f"找到 {len(chipsets)} 個唯一的 chipset")
    print(f"找到 {len(gpu_names)} 個標準 GPU 名稱")

    # 建立 prompt 內容
    prompt = f"""你是 GPU 型號對應專家。請將 CoolPC 原價屋的顯卡分類名稱（chipset）對應到標準 GPU 型號（來自 gpus.db）。

## 對應規則：

1. **提取核心型號**，對應到標準名稱：
   - "AMD RX550" → "AMD Radeon RX 550"
   - "AMD RX5500XT" → "AMD Radeon RX 5500 XT"
   - "NVIDIA RTX4090" → "NVIDIA GeForce RTX 4090"
   - "INTEL Arc B580" → "Intel Arc B580"

2. **以下類型對應到 null**：
   - 配件、轉接盒
   - 專業繪圖卡（Quadro、工作站級）
   - 周邊配件

3. **必須使用標準 GPU 型號列表中的完整名稱**

---

## 標準 GPU 型號列表（來自 gpus.db）：

```json
{json.dumps(gpu_names, ensure_ascii=False, indent=2)}
```

---

## 待對應的 CoolPC chipset 列表（來自 vga.db）：

```json
{json.dumps(chipsets, ensure_ascii=False, indent=2)}
```

---

## 輸出格式要求：

請以 JSON 格式回答，key 是 CoolPC 的 chipset，value 是標準 GPU 型號名稱或 null：

```json
{{
  "CoolPC chipset": "標準 GPU 型號",
  "AMD RX550": "AMD Radeon RX 550",
  "配件類": null,
  ...
}}
```

**重要：只輸出 JSON 物件，不要任何其他文字或說明。**
"""

    # 儲存到 txt 檔案
    output_file = "3.1 chatgpt_prompt.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(prompt)

    print(f"\n✓ Prompt 已儲存到 {output_file}")
    print(f"  檔案大小: {len(prompt)} 字元")
    print(f"\n使用方式：")
    print(f"  1. 開啟 {output_file}")
    print(f"  2. 複製全部內容")
    print(f"  3. 貼到 ChatGPT")
    print(f"  4. 將回應的 JSON 儲存為 '3 gpu_mapping_checklist.json'")

    # 關閉連接
    vga_conn.close()
    gpus_conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("ChatGPT Prompt 產生器")
    print("=" * 60)
    print()

    generate_chatgpt_prompt()
