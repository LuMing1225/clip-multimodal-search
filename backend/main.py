# -*- coding: utf-8 -*-
"""
FastAPI 后端主入口
端口 8565，CORS 中间件，静态文件服务（商品图片）。
启动时初始化 SharedMemoryStore / VectorStore / VoiceRecognizer，
并尝试加载 CLIP 模型到 GPU。
"""
import os
import sys

# 强制离线模式：模型已本地缓存，避免启动时远程检查超时
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 确保项目根目录在 sys.path 中，支持 `python backend/main.py` 直接运行
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from backend.api.routes import router, services

# ---------- 日志配置 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="CLIP电商多模态检索系统", version="1.0.0")

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 静态文件服务（商品图片） ----------
os.makedirs(config.IMAGE_DIR, exist_ok=True)
app.mount("/static/images", StaticFiles(directory=config.IMAGE_DIR), name="images")

# ---------- 路由 ----------
app.include_router(router)


@app.on_event("startup")
def startup_event() -> None:
    """启动时初始化全部服务单例。"""
    logger.info("=" * 60)
    logger.info("正在启动 CLIP 电商多模态检索系统 ...")
    try:
        # 1. 共享记忆存储（Chat/Wiki/Graph）
        from memory.shared_store import SharedMemoryStore
        services["store"] = SharedMemoryStore()

        # 2. 向量库
        from backend.core.vector_store import VectorStore
        vs = VectorStore()
        vs.create_collection()
        services["vector_store"] = vs

        # 3. 语音识别器（可选，失败自动降级）
        from backend.core.voice import VoiceRecognizer
        services["voice"] = VoiceRecognizer()

        # 4. CLIP 模型（torch 就绪时加载）
        from backend.core.clip_engine import CLIPEngine
        clip = CLIPEngine()
        clip.load_model()
        services["clip"] = clip

        # 5. 混合检索引擎 + 双 Agent（依赖 CLIP）
        from backend.core.hybrid_search import HybridSearchEngine
        from agents.intent_agent import IntentAgent
        from agents.retriever_agent import RetrieverAgent

        services["hybrid_engine"] = HybridSearchEngine(clip, vs, services["store"])
        services["intent_agent"] = IntentAgent(services["store"])
        services["retriever_agent"] = RetrieverAgent(
            services["store"], services["hybrid_engine"]
        )
        logger.info("全部服务初始化完成")
    except Exception as e:
        logger.exception("启动初始化失败（部分服务可能不可用）: %s", e)
    logger.info("=" * 60)


@app.get("/")
def root() -> dict:
    return {"code": 0, "message": "CLIP电商多模态检索系统运行中",
            "data": {"port": config.BACKEND_PORT}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=config.BACKEND_HOST,
        port=config.BACKEND_PORT,
        reload=False,
    )
