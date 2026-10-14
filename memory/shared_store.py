# -*- coding: utf-8 -*-
"""
SharedMemoryStore 统一入口
封装 ChatMemory / LLMWiki / KnowledgeGraph 三类记忆的读写操作，
提供事务性写入（一次调用同时更新 Wiki + 图谱 + 发布信号）。
"""
import logging
from typing import Any, Dict, List, Optional

from .chat.chat_memory import ChatMemory
from .wiki.llm_wiki import LLMWiki
from .graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class SharedMemoryStore:
    """共享记忆存储中心单例入口。"""

    def __init__(self) -> None:
        self.chat = ChatMemory()
        self.wiki = LLMWiki()
        self.graph = KnowledgeGraph()
        logger.info("SharedMemoryStore 初始化完成（Chat/Wiki/Graph 三件套）")

    # ---------- 事务性写入：意图偏好落库 ----------
    def write_preference(
        self,
        user_id: str,
        preferences: Dict[str, Any],
        raw_text: str = "",
    ) -> Dict[str, Any]:
        """事务性写入用户偏好：
        1) 写 LLM-Wiki（结构化 Markdown 文档）
        2) 写知识图谱偏好关系
        3) 通过 Redis Stream 发布 intent_updated 信号
        返回写入结果摘要。
        """
        result = {"wiki_id": None, "graph_updated": False, "signal_published": False}
        try:
            # 1. 生成 Markdown 文档内容
            title = f"用户偏好-{preferences.get('style', 'unknown')}"
            md_lines = [
                f"# 用户偏好记录",
                f"- 用户: {user_id}",
                f"- 原始输入: {raw_text}",
                f"- 提取时间: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 结构化偏好",
            ]
            for k in ("style", "color", "material", "category", "sentiment"):
                if preferences.get(k):
                    md_lines.append(f"- {k}: {preferences[k]}")
            content = "\n".join(md_lines)
            wiki_id = self.wiki.add_document(
                user_id=user_id,
                title=title,
                content=content,
                metadata=preferences,
            )
            result["wiki_id"] = wiki_id

            # 2. 写图谱关系
            self.graph.add_node("User", user_id)
            if preferences.get("style"):
                self.graph.add_edge("User", user_id, "PREFERS",
                                    "Style", preferences["style"])
            if preferences.get("color"):
                self.graph.add_edge("User", user_id, "PREFERS_COLOR",
                                    "Color", preferences["color"])
            if preferences.get("material"):
                self.graph.add_edge("User", user_id, "PREFERS_MATERIAL",
                                    "Material", preferences["material"])
            result["graph_updated"] = True

            # 3. 发布信号
            self.chat.publish_signal(
                "intent_updated",
                {"user_id": user_id, "wiki_id": wiki_id,
                 "preferences": preferences},
            )
            result["signal_published"] = True
            # 持久化图谱
            self.graph.save()
        except Exception as e:
            logger.exception("write_preference 事务写入失败: %s", e)
        return result

    # ---------- 用户记忆摘要 ----------
    def get_user_summary(self, user_id: str) -> Dict[str, Any]:
        """汇总用户 Chat History + Wiki 文档 + 图谱偏好关系。"""
        chat_history = self.chat.get_history(user_id)
        wiki_docs = self.wiki.list_by_user(user_id)
        # 图谱偏好
        graph_prefs = self.graph.query(
            f"MATCH (u:User)-[r]->(t) WHERE u.id='{user_id}' RETURN t"
        )
        return {
            "user_id": user_id,
            "chat_history": chat_history,
            "wiki_documents": wiki_docs,
            "graph_preferences": graph_prefs,
        }

    def clear_user(self, user_id: str) -> None:
        """清除指定用户的全部记忆（Chat + Wiki + 图谱）。"""
        self.chat.clear_user(user_id)
        self.wiki.clear_user(user_id)
        self.graph.clear_user(user_id)
        self.graph.save()

    # ---------- 商品浏览记录（用于 VIEWED 关系） ----------
    def record_view(self, user_id: str, product: Dict[str, Any]) -> None:
        """记录用户浏览过某商品，建立 VIEWED + HAS_CATEGORY 关系。"""
        pid = str(product.get("product_id"))
        self.graph.add_node("User", user_id)
        self.graph.add_node("Product", pid, title=product.get("title", ""))
        self.graph.add_edge("User", user_id, "VIEWED", "Product", pid)
        if product.get("category"):
            self.graph.add_edge("Product", pid, "HAS_CATEGORY",
                                "Category", product["category"])
        if product.get("style"):
            self.graph.add_edge("Product", pid, "HAS_STYLE",
                                "Style", product["style"])
        self.graph.save()
