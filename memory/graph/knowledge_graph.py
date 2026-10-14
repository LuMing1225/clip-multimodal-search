# -*- coding: utf-8 -*-
"""
Knowledge Graph 模块
基于 networkx 实现的内存知识图谱（替代 Neo4j），保留 Cypher 风格查询接口。

关系定义:
    (User)-[:PREFERS]->(Style)
    (User)-[:VIEWED]->(Product)
    (Product)-[:HAS_STYLE]->(Style)
    (Product)-[:HAS_CATEGORY]->(Category)
    (User)-[:PREFERS_COLOR]->(Color)
    (User)-[:PREFERS_MATERIAL]->(Material)

提供 W_graph(User, Style_product) 路径权重计算方法，图谱持久化到 JSON 文件。
"""
import json
import os
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

import config

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """用户-商品-属性 知识图谱（networkx 实现）。"""

    def __init__(self, graph_path: Optional[str] = None) -> None:
        self.graph_path = graph_path or config.GRAPH_DB_PATH
        # 使用 MultiDiGraph 支持同一对节点间多种关系
        self.G: nx.MultiDiGraph = nx.MultiDiGraph()
        self.load()

    # ---------- 节点操作 ----------
    def _nid(self, label: str, node_id: str) -> str:
        """生成带标签的全局唯一节点 id，例如 User:user_001。"""
        return f"{label}:{node_id}"

    def add_node(self, label: str, node_id: str, **props: Any) -> str:
        """添加节点，返回节点全局 id。"""
        nid = self._nid(label, node_id)
        if not self.G.has_node(nid):
            self.G.add_node(nid, label=label, node_id=node_id, **props)
        else:
            # 已存在则合并属性
            self.G.nodes[nid].update(props)
        return nid

    # ---------- 关系操作 ----------
    def add_edge(self, src_label: str, src_id: str, rel: str,
                 dst_label: str, dst_id: str, weight: float = 1.0) -> None:
        """添加带类型的有向关系。"""
        s = self.add_node(src_label, src_id)
        d = self.add_node(dst_label, dst_id)
        # 同一 (s, rel, d) 已存在则更新权重
        for k in self.G[s].get(d, {}):
            if self.G[s][d][k].get("rel") == rel:
                self.G[s][d][k]["weight"] = weight
                return
        self.G.add_edge(s, d, rel=rel, weight=weight)

    # ---------- Cypher 风格查询 ----------
    def query(self, cypher_like: str) -> List[Dict[str, Any]]:
        """极简 Cypher 风格查询接口（演示用）。

        支持形如:
            "MATCH (u:User)-[:PREFERS]->(s:Style) WHERE u.id='user_001' RETURN s"
        解析 WHERE 条件中的 id 等值匹配，返回命中的目标节点列表。
        """
        results: List[Dict[str, Any]] = []
        try:
            # 提取关系类型
            rel = None
            if "-[" in cypher_like and "]->" in cypher_like:
                seg = cypher_like.split("-[")[1].split("]->")[0]
                # 仅当显式指定关系类型（含冒号，如 [:PREFERS]）时才过滤；
                # 否则 [] 内只是变量名（如 [r]），表示不过滤关系类型
                if ":" in seg:
                    rel = seg.split(":")[-1].strip("[] ")
                else:
                    rel = None
            # 提取 WHERE 条件
            src_label, src_id = None, None
            if "WHERE" in cypher_like:
                cond = cypher_like.split("WHERE")[1].split("RETURN")[0].strip()
                # 形如 u.id='user_001'，用正则取出引号内的值
                m = re.search(r"\.id\s*=\s*['\"]([^'\"]+)['\"]", cond)
                if m:
                    src_id = m.group(1)
            # 推断源节点标签
            if "User" in cypher_like.split("MATCH")[1].split("-")[0]:
                src_label = "User"
            if src_id is None:
                return results
            src_nid = self._nid(src_label, src_id)
            if not self.G.has_node(src_nid):
                return results
            # 遍历出边
            for _, dst, data in self.G.out_edges(src_nid, data=True):
                if rel and data.get("rel") != rel:
                    continue
                results.append(
                    {
                        "target": dst,
                        "label": self.G.nodes[dst].get("label"),
                        "weight": data.get("weight", 1.0),
                        "rel": data.get("rel"),
                        "props": dict(self.G.nodes[dst]),
                    }
                )
        except Exception as e:  # 解析失败不影响主流程
            logger.warning("Cypher 查询解析失败: %s | %s", cypher_like, e)
        return results

    # ---------- W_graph 路径权重 ----------
    def w_graph(self, user_id: str, product: Dict[str, Any]) -> float:
        """计算 W_graph(User, Style_product) 路径偏好权重。

        遍历用户的偏好关系（PREFERS / PREFERS_COLOR / PREFERS_MATERIAL / VIEWED），
        与商品的 style / color / material / category 属性做匹配：
          - 风格偏好命中: 权重 1.0
          - 颜色偏好命中: 权重 0.6
          - 材质偏好命中: 权重 0.5
          - 浏览过同类目(VIEWED->Product->HAS_CATEGORY): 权重 0.3
        最终返回归一化到 [0,1] 的加权和。
        """
        src = self._nid("User", user_id)
        if not self.G.has_node(src):
            return 0.0
        # 收集用户偏好
        pref_style = set()
        pref_color = set()
        pref_material = set()
        viewed_categories = set()
        for _, dst, data in self.G.out_edges(src, data=True):
            rel = data.get("rel")
            dst_node = self.G.nodes.get(dst, {})
            dst_id = dst_node.get("node_id", dst.split(":", 1)[-1])
            if rel == "PREFERS":
                pref_style.add(dst_id)
            elif rel == "PREFERS_COLOR":
                pref_color.add(dst_id)
            elif rel == "PREFERS_MATERIAL":
                pref_material.add(dst_id)
            elif rel == "VIEWED":
                # 沿 Product -[:HAS_CATEGORY]-> Category 找类目
                for _, cat, d2 in self.G.out_edges(dst, data=True):
                    if d2.get("rel") == "HAS_CATEGORY":
                        viewed_categories.add(
                            self.G.nodes.get(cat, {}).get("node_id")
                        )

        score = 0.0
        if product.get("style") in pref_style:
            score += 1.0
        if product.get("color") in pref_color:
            score += 0.6
        if product.get("material") in pref_material:
            score += 0.5
        if product.get("category") in viewed_categories:
            score += 0.3
        # 归一化: 满分为 1.0+0.6+0.5+0.3=2.4
        return round(min(score / 2.4, 1.0), 4)

    # ---------- 统计 ----------
    def stats(self) -> Dict[str, int]:
        """返回节点数与边数。"""
        return {"nodes": self.G.number_of_nodes(), "edges": self.G.number_of_edges()}

    # ---------- 持久化 ----------
    def save(self) -> None:
        """将图谱序列化保存为 JSON。"""
        data = nx.node_link_data(self.G, edges="links")
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info("知识图谱已保存: %s", self.graph_path)

    def load(self) -> None:
        """从 JSON 文件加载图谱（文件不存在则为空图）。"""
        if not os.path.exists(self.graph_path):
            return
        try:
            with open(self.graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.G = nx.node_link_graph(data, edges="links", directed=True,
                                        multigraph=True)
            logger.info("知识图谱已加载: %s", self.graph_path)
        except Exception as e:
            logger.warning("知识图谱加载失败，使用空图: %s", e)
            self.G = nx.MultiDiGraph()

    def clear_user(self, user_id: str) -> None:
        """删除用户节点及其关联边。"""
        src = self._nid("User", user_id)
        if self.G.has_node(src):
            self.G.remove_node(src)
