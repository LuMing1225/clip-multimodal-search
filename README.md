# 基于CLIP的电商多模态检索与用户跨模态长期记忆图谱系统

## 项目简介

本系统实现了一个电商场景下的多模态检索平台，核心特色是**双Agent协同机制**与**跨模态长期记忆图谱**。用户通过文本、图片、语音表达偏好后，系统能构建长期记忆，并在后续查询中基于记忆进行精准推荐。

## 系统架构

```
用户输入层: 文本 / 图片 / 语音
    │
    ▼
双Agent层: ┌──────────────┐    Redis Stream信号     ┌──────────────┐
           │ 意图分析Agent  │ ────────────────────► │ 检索实现Agent  │
           │ (IntentAgent) │ ◄──────────────────── │ (RetrieverAgent)│
           └──────┬───────┘    订阅拉取Wiki/图谱    └──────┬───────┘
                  │                                        │
                  ▼                                        ▼
        ┌─────────────────────────────────────────────────────┐
        │              共享记忆存储中心                          │
        │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
        │  │Chat Memory│  │ LLM-Wiki │  │Knowledge-Graph   │  │
        │  │(Redis)    │  │(PostgreSQL)│ │(Neo4j)          │  │
        │  │TTL+Stream │  │Markdown  │  │实体关系图谱       │  │
        │  └──────────┘  └──────────┘  └──────────────────┘  │
        └─────────────────────────────────────────────────────┘
                  │
                  ▼
        ┌─────────────────────────┐
        │  CLIP多模态对齐 + Milvus  │
        │  512维向量空间 COSINE索引  │
        └─────────────────────────┘
                  │
                  ▼
        混合检索评分: Score = λ·cos + (1-λ)·W_graph
```

## 技术栈

| 组件 | 技术选型 | 演示版替代 |
|------|---------|-----------|
| 后端框架 | FastAPI | - |
| 多模态模型 | Chinese-CLIP-ViT-B-16 | - |
| 向量数据库 | Milvus | Milvus Lite (嵌入式) |
| Chat Memory | Redis | fakeredis (内存) |
| LLM-Wiki | PostgreSQL | SQLite |
| Knowledge-Graph | Neo4j | networkx (内存图) |
| LLM推理 | Ollama (qwen2.5:7b) | - |
| 语音转文本 | Whisper | faster-whisper (可选) |
| 前端 | 纯HTML/CSS/JS SPA | - |

## 混合检索评分公式

$$Score_{final} = \lambda \cdot \cos(V_{query\_text}, V_{product\_img}) + (1-\lambda) \cdot W_{graph}(User, Style_{product})$$

- λ 默认 0.7（CLIP语义相似度权重）
- W_graph: 基于知识图谱路径权重计算的用户偏好分

## 快速开始

### 环境要求
- NVIDIA GPU (推荐8GB+显存)
- Python 3.10+ (使用 nlp conda 环境)
- Ollama 服务运行中 (端口11434)，已拉取 qwen2.5:7b 模型

### 1. 数据初始化
```bash
init_data.bat
```
或手动执行:
```bash
set PYTHONPATH=E:\shixunXM\工单4\05-CLIP电商多模态检索系统
C:\Users\luming\anaconda3\envs\nlp\python.exe scripts/generate_dataset.py
C:\Users\luming\anaconda3\envs\nlp\python.exe scripts/init_data.py
```

### 2. 启动系统
```bash
start.bat
```
或手动启动:
```bash
# 后端 (端口8565)
set PYTHONPATH=E:\shixunXM\工单4\05-CLIP电商多模态检索系统
set HF_HUB_OFFLINE=1
C:\Users\luming\anaconda3\envs\nlp\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8565

# 前端 (端口8525)
C:\Users\luming\anaconda3\envs\nlp\python.exe frontend\serve.py
```

### 3. 访问
- 前端: http://localhost:8525
- 后端API: http://localhost:8565
- 系统状态: http://localhost:8565/api/stats

## 项目结构

```
05-CLIP电商多模态检索系统/
├── backend/                # 后端
│   ├── api/routes.py       # API路由
│   ├── core/               # 核心引擎
│   │   ├── clip_engine.py  # CLIP编码引擎
│   │   ├── vector_store.py # Milvus向量库
│   │   ├── hybrid_search.py# 混合检索
│   │   └── voice.py        # 语音转文本
│   ├── models/schemas.py   # Pydantic模型
│   └── main.py             # FastAPI入口
├── frontend/               # 前端SPA
│   ├── index.html
│   ├── css/style.css
│   ├── js/                 # api.js, app.js, search.js等
│   └── serve.py            # 静态文件服务
├── agents/                 # 双Agent
│   ├── intent_agent.py     # 意图分析Agent
│   ├── retriever_agent.py  # 检索实现Agent
│   └── prompts/            # Agent提示词
├── memory/                 # 共享记忆存储
│   ├── shared_store.py     # 统一入口
│   ├── chat/               # Chat Memory (fakeredis)
│   ├── wiki/               # LLM-Wiki (SQLite)
│   └── graph/              # Knowledge-Graph (networkx)
├── tests/harness/          # Agent Harness测试
├── scripts/                # 脚本
│   ├── generate_dataset.py # 数据集生成
│   ├── init_data.py        # 数据入库
│   └── benchmark_shared_memory.py # 压测
├── docs/                   # 文档
├── data/                   # 数据
│   ├── products/           # 商品元数据JSON
│   └── images/             # 商品图片
├── config.py               # 全局配置
├── start.bat               # 一键启动
├── init_data.bat           # 一键初始化
└── requirements.txt        # 依赖清单
```

## API接口

| 接口 | 方法 | 说明 |
|------|------|------|
| /api/search | POST | 文本搜图/混合检索 |
| /api/search/image | POST | 图搜图 |
| /api/analyze | POST | 意图分析 |
| /api/voice | POST | 语音转文本 |
| /api/memory | GET/POST/DELETE | 记忆读写 |
| /api/stats | GET | 系统状态 |
| /api/demo/collaboration | POST | 双Agent协同演示 |
| /api/images/{filename} | GET | 商品图片 |

## 验收红线

- ✅ 双Agent跨共享记忆上下文传递无损率 = 100%
- ✅ 跨模态长记忆商品Top-5召回率 ≥ 90%
- ✅ 高并发下共享记忆数据同步时延 ≤ 100ms
- ✅ CLIP混合检索平均耗时 ≤ 250ms

## 演示流程

1. 打开前端 http://localhost:8525
2. 在"多模态检索"页输入"北欧风蓝色布艺沙发"进行搜索
3. 在"双Agent协同演示"页执行完整演示:
   - 初始输入"我喜欢这款北欧风蓝色布艺沙发"
   - 意图Agent提取偏好并写入记忆
   - 后续查询"帮我推荐适合这款沙发的茶几"
   - 检索Agent基于记忆返回精准推荐
4. 在"用户记忆中心"查看构建的偏好文档和知识图谱
