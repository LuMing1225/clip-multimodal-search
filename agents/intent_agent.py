# -*- coding: utf-8 -*-
"""
意图分析 Agent
调用本地 Ollama(qwen2.5:7b) 从用户文本中提取结构化偏好
(style/color/material/category/sentiment)，写入 LLM-Wiki，
向知识图谱写入偏好关系，并通过 Redis Stream 发布 intent_updated 信号。
"""
import json
import logging
import os
import re
from typing import Any, Dict, Optional

import requests

import config

logger = logging.getLogger(__name__)

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def _read_prompt(name: str) -> str:
    """读取 agents/prompts 下的提示词文件。"""
    path = os.path.join(PROMPT_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class IntentAgent:
    """用户意图分析 Agent。"""

    def __init__(self, shared_store) -> None:
        self.store = shared_store
        self.base_url = config.OLLAMA_BASE_URL
        self.model = config.OLLAMA_INTENT_MODEL
        self.timeout = config.OLLAMA_TIMEOUT
        self.intent_prompt = _read_prompt("intent_prompt.txt")
        # 枚举词表，用于规则降级提取
        self._style_map = {
            "北欧": "Nordic", "nordic": "Nordic",
            "现代": "Modern", "modern": "Modern",
            "古典": "Classic", "classic": "Classic",
            "简约": "Minimalist", "极简": "Minimalist", "minimalist": "Minimalist",
            "工业": "Industrial", "industrial": "Industrial",
            "复古": "Vintage", "vintage": "Vintage",
        }

    # ---------- Ollama 调用 ----------
    def _call_ollama(self, prompt: str) -> Optional[str]:
        """POST 到 Ollama /api/generate，返回生成文本。"""
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as e:
            logger.warning("Ollama 调用失败: %s", e)
            return None

    @staticmethod
    def ollama_connected() -> bool:
        """探测 Ollama 是否在线。"""
        try:
            r = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # ---------- 偏好提取 ----------
    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """从文本提取结构化偏好（LLM 优先，规则降级）。"""
        prompt = self.intent_prompt + "\n用户输入: " + text + "\n"
        raw = self._call_ollama(prompt)
        prefs: Dict[str, Any] = {}
        if raw:
            prefs = self._parse_json(raw)
        # LLM 失败或字段缺失 -> 规则降级
        if not prefs:
            prefs = self._rule_based_extract(text)
        # 字段规整：缺失置 None
        for k in ("style", "color", "material", "category", "sentiment"):
            prefs.setdefault(k, None)
        return prefs

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        """从 LLM 输出中解析 JSON 对象。"""
        try:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
        return {}

    def _rule_based_extract(self, text: str) -> Dict[str, Any]:
        """规则降级：基于枚举词表匹配偏好。"""
        prefs: Dict[str, Any] = {}
        for kw, val in self._style_map.items():
            if kw in text.lower():
                prefs["style"] = val
                break
        for c in config.PRODUCT_COLORS:
            if c in text:
                prefs["color"] = c
                break
        for m in config.PRODUCT_MATERIALS:
            if m in text:
                prefs["material"] = m
                break
        for cat in config.PRODUCT_CATEGORIES:
            if cat in text:
                prefs["category"] = cat
                break
        if any(w in text for w in ["喜欢", "好看", "不错", "酷", "温馨", "爱"]):
            prefs["sentiment"] = "positive"
        elif any(w in text for w in ["不喜欢", "丑", "差"]):
            prefs["sentiment"] = "negative"
        else:
            prefs["sentiment"] = "neutral"
        return prefs

    # ---------- 完整分析流程 ----------
    def analyze(self, user_id: str, text: str,
                image_url: Optional[str] = None,
                session_id: Optional[str] = None) -> Dict[str, Any]:
        """执行完整意图分析：提取偏好 -> 落库 -> 发信号。"""
        preferences = self.extract_preferences(text)
        # 通过 SharedMemoryStore 事务性写入 Wiki + 图谱 + Stream
        wr = self.store.write_preference(user_id, preferences, raw_text=text)
        # 同时写入一条 chat 消息
        self.store.chat.save_message(user_id, "user", text, session_id=session_id)
        return {
            "preferences": preferences,
            "wiki_id": wr.get("wiki_id"),
            "graph_updated": wr.get("graph_updated", False),
            "signal_published": wr.get("signal_published", False),
        }
