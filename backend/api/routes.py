# -*- coding: utf-8 -*-
"""
API 路由实现
严格遵循 API_CONTRACT.md，统一返回 {"code", "message", "data"}。
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, UploadFile, Query
from fastapi.responses import FileResponse

import config
from backend.models.schemas import (
    AnalyzeRequest, CollaborationRequest, MemoryRequest, SearchRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------- 全局服务单例（由 main.py 启动时初始化） ----------
services: Dict[str, Any] = {}


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"code": 0, "message": "success", "data": data}


def _err(msg: str, code: int = 1) -> Dict[str, Any]:
    return {"code": code, "message": msg, "data": {}}


# ---------- 商品元数据加载 ----------
def load_products_meta() -> List[Dict[str, Any]]:
    """从 products.json 读取商品元数据。"""
    path = os.path.join(config.PRODUCT_DIR, "products.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 1. 文本搜图 / 混合检索
# ============================================================
@router.post("/api/search")
def search(req: SearchRequest) -> Dict[str, Any]:
    try:
        engine = services.get("hybrid_engine")
        if engine is None:
            return _err("检索引擎未就绪（CLIP模型未加载）", code=2)
        result = engine.search_by_text(
            query=req.query,
            user_id=req.user_id,
            mode=req.mode,
            top_k=req.top_k,
            lam=req.lambda_,
        )
        return _ok(result)
    except Exception as e:
        logger.exception("/api/search 失败: %s", e)
        return _err(f"检索失败: {e}")


# ============================================================
# 2. 图搜图
# ============================================================
@router.post("/api/search/image")
async def search_by_image(
    image: UploadFile = File(...),
    user_id: str = Form("anonymous"),
    top_k: int = Form(10),
    lam: float = Form(config.LAMBDA_WEIGHT),
) -> Dict[str, Any]:
    try:
        engine = services.get("hybrid_engine")
        if engine is None:
            return _err("检索引擎未就绪（CLIP模型未加载）", code=2)
        # 保存上传图片到临时目录
        tmp_dir = os.path.join(config.DATA_DIR, "tmp_uploads")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"q_{int(time.time()*1000)}.jpg")
        with open(tmp_path, "wb") as f:
            f.write(await image.read())
        result = engine.search_by_image(
            image_path=tmp_path, user_id=user_id, top_k=top_k, lam=lam
        )
        return _ok(result)
    except Exception as e:
        logger.exception("/api/search/image 失败: %s", e)
        return _err(f"图搜失败: {e}")


# ============================================================
# 3. 意图分析
# ============================================================
@router.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    try:
        agent = services.get("intent_agent")
        if agent is None:
            return _err("意图分析Agent未就绪", code=2)
        result = agent.analyze(
            user_id=req.user_id, text=req.text,
            image_url=req.image_url, session_id=req.session_id,
        )
        return _ok(result)
    except Exception as e:
        logger.exception("/api/analyze 失败: %s", e)
        return _err(f"意图分析失败: {e}")


# ============================================================
# 4. 语音转文本
# ============================================================
@router.post("/api/voice")
async def voice(
    audio: UploadFile = File(...),
    user_id: str = Form("anonymous"),
) -> Dict[str, Any]:
    try:
        recognizer = services.get("voice")
        # 保存音频
        os.makedirs(config.VOICE_UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
        path = os.path.join(
            config.VOICE_UPLOAD_DIR, f"{user_id}_{int(time.time())}{ext}"
        )
        with open(path, "wb") as f:
            f.write(await audio.read())
        if recognizer is None:
            return _ok({"text": "", "language": "zh", "duration_sec": 0.0,
                        "degraded": True})
        result = recognizer.transcribe(path)
        return _ok(result)
    except Exception as e:
        logger.exception("/api/voice 失败: %s", e)
        return _err(f"语音识别失败: {e}")


# ============================================================
# 5. 记忆读写
# ============================================================
@router.get("/api/memory")
def get_memory(user_id: str = Query(...)) -> Dict[str, Any]:
    try:
        store = services.get("store")
        summary = store.get_user_summary(user_id)
        return _ok(summary)
    except Exception as e:
        logger.exception("GET /api/memory 失败: %s", e)
        return _err(str(e))


@router.post("/api/memory")
def post_memory(req: MemoryRequest) -> Dict[str, Any]:
    try:
        store = services.get("store")
        if req.type == "wiki":
            wiki_id = store.wiki.add_document(
                user_id=req.user_id,
                title=req.content.get("title", "手动记录"),
                content=req.content.get("content", ""),
                metadata=req.content.get("metadata", {}),
            )
            return _ok({"wiki_id": wiki_id})
        elif req.type == "chat":
            store.chat.save_message(
                req.user_id, "user", req.content.get("text", "")
            )
            return _ok({"saved": True})
        elif req.type == "graph":
            store.write_preference(req.user_id, req.content)
            return _ok({"graph_updated": True})
        return _err("未知 memory 类型")
    except Exception as e:
        logger.exception("POST /api/memory 失败: %s", e)
        return _err(str(e))


@router.delete("/api/memory")
def delete_memory(user_id: str = Query(...)) -> Dict[str, Any]:
    try:
        store = services.get("store")
        store.clear_user(user_id)
        return _ok({"cleared": user_id})
    except Exception as e:
        logger.exception("DELETE /api/memory 失败: %s", e)
        return _err(str(e))


# ============================================================
# 6. 系统状态
# ============================================================
@router.get("/api/stats")
def stats() -> Dict[str, Any]:
    try:
        vs = services.get("vector_store")
        store = services.get("store")
        clip = services.get("clip")
        graph_stats = store.graph.stats() if store else {"nodes": 0, "edges": 0}
        wiki_count = store.wiki.count_all() if store else 0
        gpu_used = clip.gpu_memory_used_mb() if clip else 0.0
        import torch
        gpu_ok = bool(torch.cuda.is_available()) if clip and clip.loaded else False
        data = {
            "milvus_products": vs.count() if vs else 0,
            "wiki_documents": wiki_count,
            "graph_nodes": graph_stats.get("nodes", 0),
            "graph_edges": graph_stats.get("edges", 0),
            "clip_model_loaded": bool(clip and clip.loaded),
            "ollama_connected": _ollama_alive(),
            "gpu_available": gpu_ok,
            "gpu_memory_used_mb": gpu_used,
        }
        return _ok(data)
    except Exception as e:
        logger.exception("/api/stats 失败: %s", e)
        # torch 可能未装，返回降级 stats
        try:
            vs = services.get("vector_store")
            store = services.get("store")
            data = {
                "milvus_products": vs.count() if vs else 0,
                "wiki_documents": store.wiki.count_all() if store else 0,
                "graph_nodes": store.graph.stats().get("nodes", 0) if store else 0,
                "graph_edges": store.graph.stats().get("edges", 0) if store else 0,
                "clip_model_loaded": False,
                "ollama_connected": _ollama_alive(),
                "gpu_available": False,
                "gpu_memory_used_mb": 0.0,
                "note": f"torch未就绪: {e}",
            }
            return _ok(data)
        except Exception as e2:
            return _err(f"stats 失败: {e2}")


def _ollama_alive() -> bool:
    """探测 Ollama 是否在线。"""
    try:
        import requests
        r = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# ============================================================
# 7. 商品图片
# ============================================================
@router.get("/api/images/{filename}")
def get_image(filename: str) -> Any:
    try:
        path = os.path.join(config.IMAGE_DIR, filename)
        if not os.path.exists(path):
            return _err(f"图片不存在: {filename}", code=404)
        return FileResponse(path)
    except Exception as e:
        return _err(str(e))


# ============================================================
# 8. 双Agent协同演示
# ============================================================
@router.post("/api/demo/collaboration")
def collaboration(req: CollaborationRequest) -> Dict[str, Any]:
    try:
        intent = services.get("intent_agent")
        retriever = services.get("retriever_agent")
        if intent is None or retriever is None:
            return _err("Agent 未就绪", code=2)
        trace: List[Dict[str, Any]] = []
        # 第一步：意图分析 Agent 处理初始输入
        step1 = intent.analyze(req.user_id, req.initial_input)
        trace.append({"agent": "intent_agent", "action": "analyze",
                      "output": step1})
        # 第二步：检索 Agent 根据跟进问题检索
        step2 = retriever.retrieve(req.user_id, req.follow_up_query)
        trace.append({"agent": "retriever_agent", "action": "retrieve",
                      "query": req.follow_up_query,
                      "result_count": len(step2.get("results", []))})
        return _ok({
            "user_id": req.user_id,
            "trace": trace,
            "final_results": step2.get("results", []),
        })
    except Exception as e:
        logger.exception("/api/demo/collaboration 失败: %s", e)
        return _err(str(e))


# ============================================================
# 9. 数据管理
# ============================================================
@router.post("/api/admin/reindex")
def admin_reindex() -> Dict[str, Any]:
    try:
        vs = services.get("vector_store")
        clip = services.get("clip")
        if vs is None or clip is None or not clip.loaded:
            return _err("向量库或CLIP未就绪", code=2)
        from scripts.init_data import encode_and_insert
        n = encode_and_insert(clip, vs)
        return _ok({"reindexed": n})
    except Exception as e:
        logger.exception("/api/admin/reindex 失败: %s", e)
        return _err(str(e))


@router.get("/api/admin/products")
def admin_products(page: int = 1, size: int = 20) -> Dict[str, Any]:
    try:
        products = load_products_meta()
        total = len(products)
        start = (page - 1) * size
        end = start + size
        return _ok({
            "total": total,
            "page": page,
            "size": size,
            "items": products[start:end],
        })
    except Exception as e:
        logger.exception("/api/admin/products 失败: %s", e)
        return _err(str(e))
