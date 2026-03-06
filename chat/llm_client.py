"""
LLM API 封裝模組（使用 Groq API 取代原本的 Ollama）
模型預設為 llama-3.1-8b-instant
"""
import json
import logging
import re

from groq import Groq
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        # 從設定檔讀取 API Key 與模型名稱
        self.api_key = getattr(settings, "GROQ_API_KEY", "")
        self.model = getattr(settings, "GROQ_MODEL", "llama-3.1-8b-instant")
        
        if not self.api_key:
            logger.warning("未設定 GROQ_API_KEY 環境變數，呼叫 API 時將會失敗")

        self.client = Groq(api_key=self.api_key)

    def generate(self, prompt: str, system: str = "") -> str:
        """
        呼叫 Groq API 生成文字。
        回傳完整的 response 字串。
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            chat_completion = self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                temperature=0.3, # 稍微調低增加穩定性
            )
            raw = chat_completion.choices[0].message.content
            # 相容性考量：若模型仍輸出 think 標籤，將其移除
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw
        except Exception as e:
            logger.error(f"Groq 呼叫失敗：{e}")
            raise RuntimeError(f"Groq 呼叫失敗：{e}")

    def generate_json(self, prompt: str, system: str = "") -> dict | list:
        """
        呼叫 Groq 並嘗試解析 JSON 回覆。
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
