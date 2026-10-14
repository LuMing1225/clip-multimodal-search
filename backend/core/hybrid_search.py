# -*- coding: utf-8 -*-
"""
CLIP 多模态混合检索引擎
工单评分公式:
    Score_final = λ · cos(V_query_text, V_product_img) + (1-λ) · W_graph(User, Style_product)
提供 文本搜图 / 图搜图 / 混合检索 三种模式。
"""
import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

import config

logger = logging.getLogger(__name__)


class HybridSearchEngine:
    """混合检索引擎，组合 CLIP 向量相似度与图谱偏好权重。"""

    def __init__(self, clip_engine, vector_store, shared_store) -> None:
        self.clip = clip_engine
        self.vs = vector_store
        self.store = shared_store  # SharedMemoryStore（含 knowledge_graph）
        self.default_lambda = config.LAMBDA_WEIGHT
        self.top_k = config.TOP_K_RESULTS

    # ---------- 文本搜图 ----------
    def search_by_text(
        self,
        query: str,
        user_id: Optional[str] = None,
        mode: str = "hybrid",
        top_k: int = 10,
        lam: Optional[float] = None,
    ) -> Dict[str, Any]:
        """文本 -> 商品图片检索。"""
        t0 = time.time()
        lam = self.default_lambda if lam is None else lam
        # 1. 编码查询文本
        q_vec = self.clip.encode_text([query])[0]
        # 2. Milvus 召回 Top-K（先多召回一些，便于重排）
        recall = max(top_k * 3, config.TOP_K_RECALL * 3)
        candidates = self.vs.search(q_vec, top_k=recall)
        # 3. 混合评分
        results = self._rerank(candidates, user_id, mode, lam, top_k)
        latency = round((time.time() - t0) * 1000, 1)
        return {
            "query_embedding": q_vec.tolist(),
            "results": results,
            "latency_ms": latency,
        }

    # ---------- 图搜图 ----------
    def search_by_image(
        self,
        image_path: str,
        user_id: Optional[str] = None,
        mode: str = "hybrid",
        top_k: int = 10,
        lam: Optional[float] = None,
    ) -> Dict[str, Any]:
        """上传图片 -> 相似商品检索。"""
        t0 = time.time()
        lam = self.default_lambda if lam is None else lam
        q_vec = self.clip.encode_image_file(image_path)
        recall = max(top_k * 3, config.TOP_K_RECALL * 3)
        candidates = self.vs.search(q_vec, top_k=recall)
        results = self._rerank(candidates, user_id, mode, lam, top_k)
        latency = round((time.time() - t0) * 1000, 1)
        return {
            "query_embedding": q_vec.tolist(),
            "results": results,
            "latency_ms": latency,
        }

    # ---------- 混合评分重排 ----------
    def _rerank(
        self,
        candidates: List[Dict[str, Any]],
        user_id: Optional[str],
        mode: str,
        lam: float,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """按工单公式重排候选集。"""
        results: List[Dict[str, Any]] = []
        for c in candidates:
            clip_score = float(c.get("clip_score", 0.0))
            # 图谱权重 W_graph(User, Style_product)
            if mode == "hybrid" and user_id:
                g_score = self.store.graph.w_graph(user_id, c)
            else:
                g_score = 0.0
            if mode == "hybrid":
                final = lam * clip_score + (1 - lam) * g_score
            else:  # text / pure CLIP
                final = clip_score
            pid = c.get("product_id")
            code = f"P{int(pid):03d}" if isinstance(pid, (int, float)) else (pid if isinstance(pid, str) else f"P{pid}")
            results.append(
                {
                    "product_id": code,
                    "title": c.get("title"),
                    "price": c.get("price"),
                    "category": c.get("category"),
                    "style": c.get("style"),
                    "color": c.get("color"),
                    "material": c.get("material"),
                    "image_url": f"/api/images/{code}.jpg",
                    "clip_score": round(clip_score, 4),
                    "graph_score": round(g_score, 4),
                    "final_score": round(final, 4),
                }
            )
        # 按 final_score 降序
        results.sort(key=lambda x: x["final_score"], reverse=True)
        return results[:top_k]
