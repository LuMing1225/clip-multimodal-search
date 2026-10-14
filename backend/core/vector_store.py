# -*- coding: utf-8 -*-
"""
向量存储模块（Milvus Lite 封装）
集合名 ecommerce_products，字段:
    product_id(int64主键), embedding(FloatVector[512]),
    title, category, style, color, material(VarChar), price(Float)
COSINE 相似度索引；提供 插入/搜索/删除/重建 能力。
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

import config

logger = logging.getLogger(__name__)


class VectorStore:
    """Milvus Lite 向量库封装。"""

    def __init__(self) -> None:
        self.db_path = config.MILVUS_DB_PATH
        self.collection = config.MILVUS_COLLECTION
        self.dim = config.CLIP_EMBEDDING_DIM
        self.metric = config.MILVUS_METRIC_TYPE
        self.client = None
        self.connected = False
        self.connect()

    def connect(self) -> bool:
        """连接 Milvus Lite（本地文件模式）。"""
        try:
            from pymilvus import MilvusClient, DataType
            self._DataType = DataType
            # milvus-lite 要求父目录预先存在
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self.client = MilvusClient(uri=self.db_path)
            self.connected = True
            logger.info("Milvus Lite 已连接: %s", self.db_path)
            # 启动时把已有集合加载进内存，立即可查
            self.load()
            return True
        except Exception as e:
            logger.exception("Milvus 连接失败: %s", e)
            self.connected = False
            return False

    def has_collection(self) -> bool:
        return self.connected and self.client.has_collection(self.collection)

    # ---------- 建表 ----------
    def create_collection(self) -> None:
        """创建集合与 COSINE 索引。"""
        if not self.connected:
            raise RuntimeError("Milvus 未连接")
        DataType = self._DataType
        if self.client.has_collection(self.collection):
            logger.info("集合已存在: %s", self.collection)
            return
        schema = self.client.create_schema(
            auto_id=False, enable_dynamic_field=True
        )
        schema.add_field("product_id", DataType.INT64, is_primary=True)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("title", DataType.VARCHAR, max_length=256)
        schema.add_field("category", DataType.VARCHAR, max_length=64)
        schema.add_field("style", DataType.VARCHAR, max_length=64)
        schema.add_field("color", DataType.VARCHAR, max_length=64)
        schema.add_field("material", DataType.VARCHAR, max_length=64)
        schema.add_field("price", DataType.FLOAT)
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type=config.MILVUS_INDEX_TYPE,
            metric_type=self.metric,
        )
        self.client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info("集合创建完成: %s", self.collection)
        self.load()

    def load(self) -> None:
        """将集合加载到内存，供 search/get/query 使用。"""
        if self.connected and self.client.has_collection(self.collection):
            try:
                self.client.load_collection(self.collection)
            except Exception as e:
                logger.warning("load_collection 失败: %s", e)

    # ---------- 插入 ----------
    def insert_products(self, rows: List[Dict[str, Any]]) -> int:
        """批量插入商品向量与元数据，返回插入条数。"""
        if not self.connected:
            raise RuntimeError("Milvus 未连接")
        if not rows:
            return 0
        self.client.insert(collection_name=self.collection, data=rows)
        # 插入后刷新加载，使新数据可被检索
        self.load()
        return len(rows)

    # ---------- 搜索 ----------
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """向量搜索，返回带距离(COSINE相似度)的结果列表。"""
        if not self.connected:
            return []
        out_fields = ["product_id", "title", "category", "style",
                      "color", "material", "price"]
        res = self.client.search(
            collection_name=self.collection,
            data=[query_vector.tolist()],
            anns_field="embedding",
            limit=top_k,
            search_params={"metric_type": self.metric},
            output_fields=out_fields,
            filter=filter_expr,
        )
        results: List[Dict[str, Any]] = []
        for hits in res:
            for hit in hits:
                entity = hit.get("entity", {})
                results.append(
                    {
                        "product_id": entity.get("product_id"),
                        "title": entity.get("title"),
                        "category": entity.get("category"),
                        "style": entity.get("style"),
                        "color": entity.get("color"),
                        "material": entity.get("material"),
                        "price": entity.get("price"),
                        "clip_score": round(float(hit.get("distance", 0.0)), 4),
                    }
                )
        return results

    # ---------- 删除 ----------
    def delete_by_ids(self, product_ids: List[int]) -> None:
        """按主键删除商品。"""
        if not self.connected or not product_ids:
            return
        expr = f"product_id in {product_ids}"
        self.client.delete(collection_name=self.collection, filter=expr)

    # ---------- 重建 ----------
    def rebuild(self, rows: List[Dict[str, Any]]) -> int:
        """清空集合并重新插入全部数据。"""
        if not self.connected:
            raise RuntimeError("Milvus 未连接")
        self.drop_collection()
        self.create_collection()
        n = self.insert_products(rows)
        logger.info("Milvus 重建完成，共 %d 条", n)
        return n

    def drop_collection(self) -> None:
        if self.connected and self.client.has_collection(self.collection):
            self.client.drop_collection(self.collection)

    def count(self) -> int:
        """返回集合中的商品数量。"""
        if not self.connected:
            return 0
        try:
            return self.client.get_collection_stats(self.collection)["row_count"]
        except Exception:
            return 0
