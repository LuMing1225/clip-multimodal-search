# API 接口契约 (前后端共享)

后端基础URL: `http://localhost:8565`
所有接口返回 JSON，统一格式: `{"code": 0, "message": "success", "data": {...}}`

---

## 1. 文本搜图 / 混合检索
**POST** `/api/search`
- 请求体:
```json
{
  "query": "北欧风蓝色布艺沙发",
  "user_id": "user_001",
  "mode": "hybrid",
  "top_k": 10,
  "lambda": 0.7
}
```
- mode: `text`(纯文本CLIP) / `hybrid`(CLIP+图谱混合)
- 返回:
```json
{
  "code": 0,
  "data": {
    "query_embedding": [0.1, ...],
    "results": [
      {
        "product_id": "P001",
        "title": "北欧风蓝色布艺三人沙发",
        "description": "...",
        "price": 2999.0,
        "category": "家具",
        "style": "Nordic",
        "color": "蓝色",
        "material": "布艺",
        "image_url": "/api/images/P001.jpg",
        "clip_score": 0.85,
        "graph_score": 0.72,
        "final_score": 0.811
      }
    ],
    "latency_ms": 180
  }
}
```

## 2. 图搜图
**POST** `/api/search/image`
- Content-Type: `multipart/form-data`
- 字段: `image`(文件), `user_id`, `top_k`, `lambda`
- 返回: 同 `/api/search`

## 3. 意图分析
**POST** `/api/analyze`
- 请求体:
```json
{
  "user_id": "user_001",
  "text": "我喜欢这款北欧风蓝色沙发，温馨的感觉",
  "image_url": null,
  "session_id": "sess_001"
}
```
- 返回:
```json
{
  "code": 0,
  "data": {
    "preferences": {
      "style": "Nordic",
      "color": "蓝色",
      "material": "布艺",
      "category": "家具",
      "sentiment": "positive"
    },
    "wiki_id": "wiki_001",
    "graph_updated": true,
    "signal_published": true
  }
}
```

## 4. 语音转文本
**POST** `/api/voice`
- Content-Type: `multipart/form-data`
- 字段: `audio`(文件), `user_id`
- 返回:
```json
{
  "code": 0,
  "data": {
    "text": "我喜欢北欧风格的沙发",
    "language": "zh",
    "duration_sec": 3.5
  }
}
```

## 5. 记忆读写
**GET** `/api/memory?user_id=user_001`
- 返回用户的 Chat Memory + LLM-Wiki + 图谱关系摘要

**POST** `/api/memory`
- 请求体: `{"user_id": "user_001", "type": "wiki|chat|graph", "content": {...}}`

**DELETE** `/api/memory?user_id=user_001`
- 清除用户所有记忆

## 6. 系统状态
**GET** `/api/stats`
- 返回:
```json
{
  "code": 0,
  "data": {
    "milvus_products": 300,
    "wiki_documents": 5,
    "graph_nodes": 50,
    "graph_edges": 120,
    "clip_model_loaded": true,
    "ollama_connected": true,
    "gpu_available": true,
    "gpu_memory_used_mb": 2048
  }
}
```

## 7. 商品图片
**GET** `/api/images/{filename}`
- 返回商品图片文件

## 8. 双Agent协同演示
**POST** `/api/demo/collaboration`
- 请求体:
```json
{
  "user_id": "user_001",
  "initial_input": "我喜欢这款北欧风蓝色布艺沙发",
  "follow_up_query": "帮我推荐几款适合这款沙发的茶几"
}
```
- 返回完整的双Agent协同轨迹 + 最终检索结果

## 9. 数据管理
**POST** `/api/admin/reindex`
- 重新入库所有商品数据到Milvus
**GET** `/api/admin/products?page=1&size=20`
- 分页查询商品列表
