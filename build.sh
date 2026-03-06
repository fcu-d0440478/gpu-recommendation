#!/usr/bin/env bash
# exit on error
set -o errexit

echo "正在安裝套件 requirements.txt..."
pip install -r requirements.txt

echo "正在安裝 Playwright 無頭瀏覽器及其系統相依套件..."
playwright install chromium --with-deps

echo "正在收集靜態檔案 collectstatic..."
python manage.py collectstatic --no-input

echo "正在執行資料庫遷移 migrate..."
python manage.py migrate
