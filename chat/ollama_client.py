"""
Ollama API 封裝模組
模型固定為 qwen3:4b
"""
import json
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self):
        self.api_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT

    def generate(self, prompt: str, system: str = "") -> str:
        """
        呼叫 Ollama API 生成文字。
        回傳完整的 response 字串。
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        try:
            resp = requests.post(self.api_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "")
            # 移除 qwen3 的 <think>...</think> 思考區塊
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw
        except requests.exceptions.ConnectionError:
            logger.error("無法連線到 Ollama，請確認 Ollama 服務已啟動 (http://localhost:11434)")
            raise RuntimeError("Ollama 服務未啟動，請先執行 `ollama serve`")
        except requests.exceptions.Timeout:
            logger.error("Ollama 請求逾時")
            raise RuntimeError("Ollama 請求逾時，請稍後再試")
        except Exception as e:
            logger.error(f"Ollama 呼叫失敗：{e}")
            raise RuntimeError(f"Ollama 呼叫失敗：{e}")

    def generate_json(self, prompt: str, system: str = "") -> dict | list:
        """
        呼叫 Ollama 並嘗試解析 JSON 回覆。
        若解析失敗則拋出 ValueError。
        """
        raw = self.generate(prompt, system)
        # 嘗試從 markdown code block 中提取 JSON
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if match:
            raw = match.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失敗：{e}\n原始回覆：{raw}")
            raise ValueError(f"LLM 回覆格式錯誤，無法解析 JSON：{raw[:200]}")
