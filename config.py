# -*- coding: utf-8 -*-
"""
全局配置文件
基于CLIP的电商多模态检索与用户跨模态长期记忆图谱系统
"""
import os

# ========== 路径配置 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGE_DIR = os.path.join(DATA_DIR, "images")
PRODUCT_DIR = os.path.join(DATA_DIR, "products")
MODEL_DIR = os.path.join(BASE_DIR, "models")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

# ========== 服务端口 ==========
BACKEND_PORT = 8565
FRONTEND_PORT = 8525
BACKEND_HOST = "0.0.0.0"
FRONTEND_HOST = "0.0.0.0"

# ========== CLIP模型配置 ==========
CLIP_MODEL_NAME = "OFA-Sys/chinese-clip-vit-base-patch16"
CLIP_EMBEDDING_DIM = 512
CLIP_DEVICE = "cuda"  # cuda / cpu
CLIP_BATCH_SIZE = 32

# ========== Milvus Lite 配置 ==========
# 注意：milvus-lite/faiss 不支持含中文的路径，故放在纯英文目录下
MILVUS_DB_PATH = os.getenv("MILVUS_DB_PATH", os.path.join(DATA_DIR, "milvus_products.db"))
MILVUS_COLLECTION = "ecommerce_products"
MILVUS_INDEX_TYPE = "AUTOINDEX"
MILVUS_METRIC_TYPE = "COSINE"

# ========== 存储配置（轻量演示版替代） ==========
# Chat Memory: fakeredis (内存版Redis兼容层，演示版替代)
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
CHAT_MEMORY_TTL = 86400  # 24小时
REDIS_STREAM_NAME = "agent_signals"
REDIS_STREAM_CONSUMER_GROUP = "retriever_group"

# LLM-Wiki: SQLite (演示版替代PostgreSQL，Schema保持兼容)
SQLITE_DB_PATH = os.path.join(DATA_DIR, "llm_wiki.db")

# Knowledge-Graph: networkx 内存图 (演示版替代Neo4j，保留Cypher风格查询接口)
GRAPH_DB_PATH = os.path.join(DATA_DIR, "knowledge_graph.json")

# ========== Ollama LLM配置 ==========
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_INTENT_MODEL = "qwen2.5:7b"  # 意图分析Agent用
OLLAMA_TIMEOUT = 60

# ========== 语音配置 ==========
WHISPER_MODEL_SIZE = "base"  # tiny/base/small/medium
VOICE_UPLOAD_DIR = os.path.join(DATA_DIR, "voice_uploads")

# ========== 混合检索评分 ==========
LAMBDA_WEIGHT = 0.7  # CLIP相似度权重，(1-λ)为图谱偏好权重
TOP_K_RESULTS = 10
TOP_K_RECALL = 5

# ========== 数据集配置 ==========
SYNTHETIC_PRODUCT_COUNT = 300
PRODUCT_CATEGORIES = ["家具", "服饰", "数码", "家居", "美妆", "运动"]
PRODUCT_STYLES = ["Nordic", "Modern", "Classic", "Minimalist", "Industrial", "Vintage"]
PRODUCT_COLORS = ["蓝色", "白色", "黑色", "灰色", "棕色", "红色", "绿色", "米色"]
PRODUCT_MATERIALS = ["布艺", "实木", "金属", "皮革", "塑料", "玻璃", "棉麻", "陶瓷"]

# ========== 压测配置 ==========
BENCHMARK_CONCURRENT_AGENTS = 100
BENCHMARK_DURATION_SEC = 30
BENCHMARK_WARMUP_SEC = 5

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(PRODUCT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(VOICE_UPLOAD_DIR, exist_ok=True)
