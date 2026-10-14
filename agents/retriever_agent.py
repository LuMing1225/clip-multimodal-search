# -*- coding: utf-8 -*-
"""
检索实现 Agent
订阅 Redis Stream 信号，拉取用户最新偏好 Wiki，
生成 Cypher 风格查询定位目标风格，通过 CLIP 文本编码器检索 Milvus 商品，
并执行混合评分。
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


class RetrieverAgent:
    """检索实现 Agent。"""

    def __init__(self, shared_store, hybrid_engine) -> None:
        self.store = shared_store
        self.engine = hybrid_engine  # HybridSearchEngine
        with open(os.path.join(PROMPT_DIR, "retriever_prompt.txt"),
                  "r", encoding="utf-8") as f:
            self.retriever_prompt = f.read()

    # ---------- 订阅信号 ----------
    def poll_signals(self, consumer: str = "retriever_worker") -> List[Dict[str, Any]]:
        """从 Redis Stream 拉取待处理的 intent_updated 信号。"""
        return self.store.chat.consume_signals(consumer_name=consumer, count=10)

    # ---------- 生成检索 query ----------
    def build_clip_query(self, user_id: str) -> Dict[str, Any]:
        """拉取用户最新 Wiki 偏好，生成 CLIP 检索 query 与 Cypher。"""
        docs = self.store.wiki.list_by_user(user_id, limit=1)
        if not docs:
            return {"clip_query": "", "cypher": "", "preferences": {}}
        meta = docs[0].get("metadata", {})
        style = meta.get("style", "")
        color = meta.get("color", "")
        material = meta.get("material", "")
        category = meta.get("category", "")
        # 拼成中文 CLIP 检索描述
        parts = [p for p in (style, color, material) if p]
        clip_query = "".join(parts) + (" " + category if category else "")
        cypher = f"MATCH (u:User)-[:PREFERS]->(s:Style) WHERE u.id='{user_id}' RETURN s"
        return {
            "clip_query": clip_query.strip(),
            "cypher": cypher,
            "preferences": meta,
        }

    # ---------- 执行检索 ----------
    def retrieve(self, user_id: str, query: str,
                 top_k: int = 10, lam: Optional[float] = None,
                 mode: str = "hybrid") -> Dict[str, Any]:
        """根据用户输入执行混合检索。"""
        result = self.engine.search_by_text(
            query=query, user_id=user_id, mode=mode, top_k=top_k, lam=lam
        )
        # 记录浏览过的商品（建立 VIEWED 关系）
        for r in result.get("results", []):
            self.store.record_view(user_id, r)
        return result

    def handle_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理一条 intent_updated 信号：读偏好 -> 生成 query -> 检索。"""
        payload = signal.get("payload", {})
        user_id = payload.get("user_id")
        if not user_id:
            return None
        plan = self.build_clip_query(user_id)
        if not plan["clip_query"]:
            return None
        logger.info("RetrieverAgent 处理信号 user=%s query=%s",
                    user_id, plan["clip_query"])
        results = self.retrieve(user_id, plan["clip_query"])
        return {"user_id": user_id, "plan": plan, "results": results}
