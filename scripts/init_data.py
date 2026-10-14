# -*- coding: utf-8 -*-
"""
一键初始化脚本
建库建表（SQLite表 / networkx图谱 / Milvus集合），
加载 products.json，用 CLIP 编码所有商品图片向量，批量插入 Milvus，
并写入基础图谱关系（Product-[:HAS_STYLE]->Style, Product-[:HAS_CATEGORY]->Category）。
"""
import json
import logging
import os
import sys
from typing import List

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PIL import Image
from tqdm import tqdm

import config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_products() -> List[dict]:
    """读取 products.json。"""
    path = os.path.join(config.PRODUCT_DIR, "products.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"商品数据不存在，请先运行 generate_dataset.py: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def encode_and_insert(clip, vs) -> int:
    """用 CLIP 编码所有商品图片并批量写入 Milvus，返回写入条数。"""
    products = load_products()
    rows = []
    imgs = []
    codes = []
    for p in tqdm(products, desc="CLIP编码商品图"):
        pid = p["product_code"]
        img_path = os.path.join(config.IMAGE_DIR, f"{pid}.jpg")
        if not os.path.exists(img_path):
            continue
        img = Image.open(img_path).convert("RGB")
        imgs.append(img)
        codes.append(p)
    # 批量编码
    embeddings = clip.encode_images(imgs)
    for p, emb in zip(codes, embeddings):
        rows.append({
            "product_id": int(p["product_id"]),
            "embedding": emb.tolist(),
            "title": p["title"],
            "category": p["category"],
            "style": p["style"],
            "color": p["color"],
            "material": p["material"],
            "price": float(p["price"]),
        })
    n = vs.insert_products(rows)
    logger.info("已写入 Milvus %d 条商品向量", n)
    return n


def build_graph_relations(store) -> None:
    """写入基础图谱关系：Product-[:HAS_STYLE]->Style / HAS_CATEGORY。"""
    products = load_products()
    for p in products:
        pid = str(p["product_id"])
        store.graph.add_node("Product", pid, title=p["title"])
        if p.get("style"):
            store.graph.add_edge("Product", pid, "HAS_STYLE",
                                "Style", p["style"])
        if p.get("category"):
            store.graph.add_edge("Product", pid, "HAS_CATEGORY",
                                "Category", p["category"])
        if p.get("color"):
            store.graph.add_edge("Product", pid, "HAS_COLOR",
                                "Color", p["color"])
        if p.get("material"):
            store.graph.add_edge("Product", pid, "HAS_MATERIAL",
                                "Material", p["material"])
    store.graph.save()
    logger.info("基础图谱关系构建完成: %s", store.graph.stats())


def main() -> None:
    print("=" * 60)
    print("开始初始化数据 ...")
    # 1. 初始化 SQLite / 图谱（通过 SharedMemoryStore）
    from memory.shared_store import SharedMemoryStore
    store = SharedMemoryStore()
    print("[1/4] SQLite Wiki 表 + 图谱 初始化完成")

    # 2. Milvus 集合
    from backend.core.vector_store import VectorStore
    vs = VectorStore()
    vs.create_collection()
    print("[2/4] Milvus 集合就绪:", vs.collection)

    # 3. 加载 CLIP 模型并编码入库
    from backend.core.clip_engine import CLIPEngine
    clip = CLIPEngine()
    if not clip.load_model():
        print("[警告] CLIP 模型加载失败（torch可能未就绪），跳过向量入库")
        return
    n = encode_and_insert(clip, vs)
    print(f"[3/4] CLIP 编码 + Milvus 插入完成，共 {n} 条")

    # 4. 构建图谱关系
    build_graph_relations(store)
    print("[4/4] 图谱基础关系构建完成")
    print("=" * 60)
    print("初始化全部完成！Milvus 商品数 =", vs.count())


if __name__ == "__main__":
    main()
