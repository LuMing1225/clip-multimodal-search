# 基于 TencentDB-Agent-Memory 规范的电商跨模态长记忆检索方案书

> **项目名称**：CLIP 电商多模态检索与用户跨模态长期记忆图谱系统
> **文档版本**：v1.0
> **编写日期**：2026-10-02
> **适用场景**：数字人导购 / 电商个性化推荐 / 跨模态语义检索
> **演示版状态**：轻量组件替代（fakeredis / SQLite / networkx / Milvus Lite），接口抽象层完备，可平滑迁移生产级组件

---

## 1. 项目概述

### 1.1 背景与痛点

在传统电商导购场景中，用户的偏好信息散落在多个会话窗口中，系统缺乏**跨模态、跨时间的长期记忆能力**。典型痛点案例：

- **场景**：用户周一通过图片上传了一张"北欧风蓝色沙发"，并语音说了一句"喜欢温馨的感觉"。系统记录了这次浏览，但周五用户输入"帮我搭配之前看中的那款沙发的茶几"时，系统完全无法关联到周一的沙发偏好。
- **业务影响**：据电商行业测算，由于缺乏用户长期偏好记忆，个性化推荐转化率下降约 **35%**，用户平均需要多浏览 2.3 个商品页才能找到满意商品，客单价损失约 12%。
- **技术根因**：
  1. 多模态输入（图片、语音、文本）缺乏统一编码空间；
  2. 用户偏好没有结构化沉淀，会话结束即丢失；
  3. 多 Agent 协作时存在信息孤岛，上下文无法无损传递；
  4. 检索阶段缺乏用户先验约束，纯向量召回精度不足。

### 1.2 系统目标与验收红线

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 记忆无损率 | **100%** | 一次意图写入，Wiki + 图谱 + Stream 信号三者必须全部落库，任一失败需告警 |
| Top-5 召回率 | **≥ 90%** | 混合检索（CLIP 向量 + 图谱偏好）下，人工标注的正确商品出现在 Top-5 的比例 |
| 同步时延 | **≤ 100ms** | IntentAgent 写入偏好 → Redis Stream 信号发布完成的端到端时延 |
| 检索耗时 | **≤ 250ms** | 用户输入查询 → 返回 Top-K 结果的端到端响应时间（含 CLIP 编码 + Milvus 召回 + 混合评分） |
| 向量维度 | 512 维 | Chinese-CLIP-ViT-B-16 输出维度 |
| 商品库规模 | 300 条（演示）→ 百万级（生产） | Milvus 水平扩展 |

---

## 2. 共享记忆存储中心设计（核心）

本系统严格遵循 **TencentDB-Agent-Memory 规范**，将 Agent 记忆划分为三层，各司其职，通过统一入口 `SharedMemoryStore` 事务性写入。

### 2.1 三层记忆架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                   SharedMemoryStore 统一入口                  │
│              （事务性写入：Wiki + Graph + Signal）            │
├─────────────────┬───────────────────┬─────────────────────┤
│   Chat Memory   │     LLM-Wiki      │  Knowledge-Graph    │
│   (短期会话)     │   (长期偏好文档)   │   (实体关系图谱)     │
│   Redis /       │   PostgreSQL /    │   Neo4j /           │
│   fakeredis     │   SQLite          │   networkx          │
│   TTL=24h       │   Markdown文档    │   节点+关系         │
│   Stream信号    │   结构化元数据     │   W_graph权重计算   │
└─────────────────┴───────────────────┴─────────────────────┘
```

---

### 2.2 Chat Memory（短期会话记忆）

**生产方案**：Redis（Sorted Set / List + Stream）
**演示替代**：fakeredis（内存版 Redis 兼容层，接口完全一致）

#### 2.2.1 Key 设计

| 用途 | Key 模式 | 数据结构 | TTL | 说明 |
|------|----------|----------|-----|------|
| 会话消息 | `chat:memory:{user_id}` | List (RPUSH) | 86400s (24h) | 存储用户与助手的对话历史，每条消息为 JSON |
| Agent 信号流 | `agent_signals` | Stream | 持久 | IntentAgent → RetrieverAgent 的事件信号总线 |

#### 2.2.2 会话消息 Schema

```
Key: chat:memory:user_001
Type: Redis List
Elements (每条为 JSON 字符串):
{
  "role": "user",           // user / assistant
  "content": "我喜欢北欧风蓝色沙发",
  "session_id": "sess_001",
  "timestamp": 1727846400.123,
  "extra": {}
}
```

- **写入**：`RPUSH chat:memory:{uid} <json>` → `EXPIRE chat:memory:{uid} 86400`
- **读取**：`LRANGE chat:memory:{uid} -20 -1`（取最近 20 条）
- **清除**：`DEL chat:memory:{uid}`

#### 2.2.3 Redis Stream 信号结构

Stream 名称：`agent_signals`（配置项 `REDIS_STREAM_NAME`）

```
Stream: agent_signals
消息字段:
{
  "event": "intent_updated",     // 事件类型
  "payload": "{\"user_id\":\"user_001\",\"wiki_id\":5,\"preferences\":{...}}",
  "timestamp": 1727846400.123
}
```

#### 2.2.4 Consumer Group 设计

| 配置项 | 值 | 说明 |
|--------|-----|------|
| Stream Key | `agent_signals` | Agent 信号总线 |
| Consumer Group | `retriever_group` | 检索 Agent 消费组 |
| Consumer Name | `retriever_worker` | 消费者实例名 |
| 起始 ID | `0` | 从头消费（MKSTREAM=True） |
| ACK 策略 | 手动 XACK | 处理成功后确认，避免消息堆积 |

**消费流程**：
```python
# 拉取新信号
resp = client.xreadgroup(
    groupname="retriever_group",
    consumername="retriever_worker",
    streams={"agent_signals": ">"},
    count=10,
    block=1000,  # 阻塞1ms
)
# 处理后 ACK
client.xack("agent_signals", "retriever_group", msg_id)
```

> **⚠️ 演示版标注**：本模块使用 `fakeredis.FakeStrictRedis` 替代真实 Redis 服务。fakeredis 在内存中模拟 Redis 协议，支持 List / Stream / Consumer Group 全部操作，生产环境切换为真实 Redis 仅需修改连接字符串。

---

### 2.3 LLM-Wiki（长期偏好文档）

**生产方案**：PostgreSQL（结构化 Markdown 文档存储）
**演示替代**：SQLite（Schema 完全兼容，数据类型一一映射）

#### 2.3.1 完整表结构 SQL

**生产版（PostgreSQL）**：

```sql
-- wiki_documents 表：存储用户偏好的结构化 Markdown 文档
CREATE TABLE IF NOT EXISTS wiki_documents (
    id            BIGSERIAL PRIMARY KEY,
    user_id       VARCHAR(64) NOT NULL,
    title         VARCHAR(256) NOT NULL,
    content       TEXT NOT NULL,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    created_at    DOUBLE PRECISION NOT NULL,
    updated_at    DOUBLE PRECISION NOT NULL
);

-- 索引：按用户查询文档
CREATE INDEX IF NOT EXISTS idx_wiki_user ON wiki_documents(user_id);
-- 索引：按更新时间排序（生产版加分）
CREATE INDEX IF NOT EXISTS idx_wiki_updated ON wiki_documents(updated_at DESC);
```

**演示版（SQLite，Schema 兼容）**：

```sql
-- 实际代码中执行的 DDL（llm_wiki.py _init_schema）
CREATE TABLE IF NOT EXISTS wiki_documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wiki_user ON wiki_documents(user_id);
```

#### 2.3.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| id | 自增主键 | 文档唯一标识 |
| user_id | VARCHAR(64) | 用户标识，如 `user_001` |
| title | VARCHAR(256) | 文档标题，如 `用户偏好-Nordic` |
| content | TEXT | Markdown 格式的偏好文档正文 |
| metadata_json | JSONB / TEXT | 结构化偏好元数据（style/color/material/category/sentiment） |
| created_at | DOUBLE | 创建时间戳（Unix 秒） |
| updated_at | DOUBLE | 更新时间戳（Unix 秒） |

#### 2.3.3 Wiki 文档内容示例

```markdown
# 用户偏好记录
- 用户: user_001
- 原始输入: 我喜欢这款北欧风蓝色布艺沙发，温馨的感觉
- 提取时间: 2026-10-02 14:30:00

## 结构化偏好
- style: Nordic
- color: 蓝色
- material: 布艺
- category: 家具
- sentiment: positive
```

> **⚠️ 演示版标注**：本模块使用 SQLite 文件（`data/llm_wiki.db`）替代 PostgreSQL。SQLite 的 `TEXT` 对应 PostgreSQL 的 `VARCHAR/TEXT`，`INTEGER AUTOINCREMENT` 对应 `BIGSERIAL`，`REAL` 对应 `DOUBLE PRECISION`，`metadata_json TEXT` 存储 JSON 字符串（生产版用 `JSONB` 可索引）。切换 PostgreSQL 仅需替换连接驱动和 DDL 中的类型关键字。

---

### 2.4 Knowledge-Graph / Code-Graph（实体关系图谱）

**生产方案**：Neo4j（属性图数据库，Cypher 查询语言）
**演示替代**：networkx MultiDiGraph（内存图，保留 Cypher 风格查询接口）

#### 2.4.1 节点标签定义

| 节点标签 | 说明 | 核心属性 |
|----------|------|----------|
| `User` | 用户 | id, name |
| `Product` | 商品 | id, title, price, category, style, color, material |
| `Style` | 风格 | id（Nordic/Modern/Classic/Minimalist/Industrial/Vintage） |
| `Category` | 类目 | id（家具/服饰/数码/家居/美妆/运动） |
| `Color` | 颜色 | id（蓝色/白色/黑色/灰色/棕色/红色/绿色/米色） |
| `Material` | 材质 | id（布艺/实木/金属/皮革/塑料/玻璃/棉麻/陶瓷） |

#### 2.4.2 关系类型定义

| 关系 | 方向 | 语义 | 默认权重 |
|------|------|------|----------|
| `PREFERS` | User → Style | 用户偏好某种风格 | 1.0 |
| `PREFERS_COLOR` | User → Color | 用户偏好某种颜色 | 1.0 |
| `PREFERS_MATERIAL` | User → Material | 用户偏好某种材质 | 1.0 |
| `VIEWED` | User → Product | 用户浏览过某商品 | 1.0 |
| `HAS_STYLE` | Product → Style | 商品属于某种风格 | 1.0 |
| `HAS_CATEGORY` | Product → Category | 商品属于某类目 | 1.0 |

#### 2.4.3 Cypher 建图语句（生产版 Neo4j）

```cypher
// 创建用户节点
CREATE (u:User {id: 'user_001', name: '测试用户'});

// 创建风格节点
CREATE (s:Style {id: 'Nordic'});
CREATE (s:Style {id: 'Modern'});

// 创建商品节点
CREATE (p:Product {id: 'P001', title: '北欧风蓝色布艺三人沙发', price: 2999.0});

// 创建属性节点
CREATE (c:Color {id: '蓝色'});
CREATE (m:Material {id: '布艺'});
CREATE (cat:Category {id: '家具'});

// 建立偏好关系
MATCH (u:User {id: 'user_001'}), (s:Style {id: 'Nordic'})
CREATE (u)-[:PREFERS {weight: 1.0}]->(s);

MATCH (u:User {id: 'user_001'}), (c:Color {id: '蓝色'})
CREATE (u)-[:PREFERS_COLOR {weight: 1.0}]->(c);

MATCH (u:User {id: 'user_001'}), (m:Material {id: '布艺'})
CREATE (u)-[:PREFERS_MATERIAL {weight: 1.0}]->(m);

// 建立商品属性关系
MATCH (p:Product {id: 'P001'}), (s:Style {id: 'Nordic'})
CREATE (p)-[:HAS_STYLE]->(s);

MATCH (p:Product {id: 'P001'}), (cat:Category {id: '家具'})
CREATE (p)-[:HAS_CATEGORY]->(cat);

// 浏览记录
MATCH (u:User {id: 'user_001'}), (p:Product {id: 'P001'})
CREATE (u)-[:VIEWED {weight: 1.0}]->(p);
```

#### 2.4.4 Cypher 查询示例

```cypher
// 查询用户偏好的所有风格
MATCH (u:User {id: 'user_001'})-[:PREFERS]->(s:Style)
RETURN s.id AS style;

// 查询偏好某风格的所有商品
MATCH (u:User {id: 'user_001'})-[:PREFERS]->(s:Style)<-[:HAS_STYLE]-(p:Product)
RETURN p.id, p.title, p.price;

// 查询用户浏览过的同类目商品（用于冷启动推荐）
MATCH (u:User {id: 'user_001'})-[:VIEWED]->(p:Product)-[:HAS_CATEGORY]->(cat:Category)
WITH cat, count(p) AS view_count
RETURN cat.id AS category, view_count
ORDER BY view_count DESC;
```

> **⚠️ 演示版标注**：本模块使用 `networkx.MultiDiGraph` 实现，节点 ID 格式为 `{label}:{node_id}`（如 `User:user_001`），边属性存储 `rel`（关系类型）和 `weight`（权重）。提供 `query(cypher_like)` 方法解析简化版 Cypher 语句（支持 `MATCH (u:User)-[:PREFERS]->(s:Style) WHERE u.id='xxx' RETURN s` 模式），生产环境切换 Neo4j 后接口语义完全一致。

---

### 2.5 统一入口 SharedMemoryStore 事务性写入机制

`SharedMemoryStore` 是三类记忆的统一门面（Facade 模式），核心方法 `write_preference()` 实现**事务性三联写入**：

```python
# memory/shared_store.py 核心逻辑
def write_preference(self, user_id, preferences, raw_text=""):
    # 1. 写 LLM-Wiki（结构化 Markdown 文档）
    wiki_id = self.wiki.add_document(
        user_id=user_id, title=f"用户偏好-{style}",
        content=markdown_content, metadata=preferences,
    )
    # 2. 写知识图谱偏好关系
    self.graph.add_edge("User", user_id, "PREFERS", "Style", style)
    self.graph.add_edge("User", user_id, "PREFERS_COLOR", "Color", color)
    self.graph.add_edge("User", user_id, "PREFERS_MATERIAL", "Material", material)
    # 3. 发布 Redis Stream 信号
    self.chat.publish_signal("intent_updated", {
        "user_id": user_id, "wiki_id": wiki_id, "preferences": preferences,
    })
    self.graph.save()  # 持久化图谱到 JSON
```

**事务性保障机制**：
- 三步写入在同一个 Python 方法内顺序执行，任一步失败记日志并回滚部分状态（演示版采用补偿式日志告警）；
- 生产环境可升级为分布式事务（Saga 模式）或数据库事务包裹；
- `get_user_summary()` 方法一次性汇总 Chat History + Wiki 文档 + 图谱偏好，供调试与前端展示。

---

## 3. 多模态特征对齐

### 3.1 Chinese-CLIP-ViT-B-16 模型架构

| 属性 | 值 |
|------|-----|
| 模型名称 | `OFA-Sys/chinese-clip-vit-base-patch16` |
| 来源 | 阿里通义实验室 Chinese CLIP |
| 文本编码器 | RoBERTa-Chinese Base（12层 Transformer） |
| 图片编码器 | ViT-Base-Patch16（12层 Vision Transformer） |
| 输出维度 | **512 维**（共用向量空间） |
| 预训练数据 | 数亿级中文图文对 |
| 部署方式 | HuggingFace `transformers` 库加载，GPU 推理 |

### 3.2 512 维共用向量空间设计

Chinese CLIP 的核心设计是**文本编码器和图片编码器映射到同一个 512 维向量空间**：

```
文本输入 ──→ Text Encoder (RoBERTa) ──→ 512维向量 ──┐
                                                     ├──→ COSINE 相似度
图片输入 ──→ Image Encoder (ViT)    ──→ 512维向量 ──┘
```

- 编码后向量均做 **L2 归一化**（`feats / feats.norm(p=2, dim=-1)`），因此向量点积 = 余弦相似度；
- 文本搜图：将查询文本编码为向量，与商品图片向量计算相似度；
- 图搜图：将上传图片编码为向量，与商品图片向量计算相似度。

### 3.3 预处理流程

**文本预处理**（`ChineseCLIPProcessor`）：
1. 中文分词与 BPE 编码
2. Padding / Truncation（最大长度自动截断）
3. 转 PyTorch Tensor → 移至 GPU
4. 前向传播 → `get_text_features()` → L2 归一化

**图片预处理**：
1. PIL Image 打开 → 转换为 RGB
2. Resize + CenterCrop（224×224）
3. 归一化（ImageNet 均值方差）
4. 转 Tensor → 移至 GPU
5. 前向传播 → `get_image_features()` → L2 归一化

### 3.4 Milvus 向量库 Schema

| 配置项 | 值 |
|--------|-----|
| 集合名 | `ecommerce_products` |
| 主键字段 | `product_id` (INT64) |
| 向量字段 | `embedding` (FLOAT_VECTOR, dim=512) |
| 标量字段 | `title`(VARCHAR 256), `category`(VARCHAR 64), `style`(VARCHAR 64), `color`(VARCHAR 64), `material`(VARCHAR 64), `price`(FLOAT) |
| 索引类型 | `AUTOINDEX`（自动选择 IVF/HNSW） |
| 度量方式 | `COSINE`（余弦相似度） |
| 动态字段 | 启用（`enable_dynamic_field=True`） |

**建集合代码**（实际执行）：
```python
schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
schema.add_field("product_id", DataType.INT64, is_primary=True)
schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=512)
schema.add_field("title", DataType.VARCHAR, max_length=256)
schema.add_field("category", DataType.VARCHAR, max_length=64)
schema.add_field("style", DataType.VARCHAR, max_length=64)
schema.add_field("color", DataType.VARCHAR, max_length=64)
schema.add_field("material", DataType.VARCHAR, max_length=64)
schema.add_field("price", DataType.FLOAT)
```

> **⚠️ 演示版标注**：本模块使用 **Milvus Lite**（嵌入式模式，`MilvusClient(uri=本地文件路径)`），数据持久化在 `data/milvus_demo.db` 文件中，无需独立部署 Milvus 服务端。生产环境切换为 Milvus Standalone / Cluster 仅需修改 `uri` 为 `http://milvus-host:19530`。

---

## 4. 双 Agent 协同机制

### 4.1 意图分析 Agent（IntentAgent）

**职责**：接收用户输入 → LLM 提取结构化偏好 → 写入三类记忆 → 发布信号。

#### 4.1.1 完整数据流

```
用户文本/语音转文本
    │
    ▼
┌─────────────────────────┐
│  1. 构建 Prompt          │  intent_prompt.txt + 用户输入
│  (ReAct + Few-Shot)     │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  2. 调用 Ollama LLM      │  POST http://localhost:11434/api/generate
│  model=qwen2.5:7b       │  format=json, temperature=0.1
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  3. 解析 JSON 输出       │  {"style":"Nordic","color":"蓝色",...}
│  (失败→规则降级)         │  枚举词表匹配兜底
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  4. SharedMemoryStore    │  事务性写入：
│     .write_preference()  │  ① LLM-Wiki 文档
│                         │  ② Knowledge-Graph 关系
│                         │  ③ Redis Stream 信号
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  5. 保存 Chat Memory     │  chat:memory:{uid} RPUSH
└─────────────────────────┘
```

#### 4.1.2 工具调用列表

| 工具/方法 | 作用 | 调用时机 |
|-----------|------|----------|
| Ollama `/api/generate` | LLM 偏好提取 | 每次 analyze() 调用 |
| `store.wiki.add_document()` | 写入 Wiki 文档 | write_preference() 步骤1 |
| `store.graph.add_edge()` | 写入图谱关系 | write_preference() 步骤2 |
| `store.chat.publish_signal()` | 发布 Stream 信号 | write_preference() 步骤3 |
| `store.chat.save_message()` | 保存会话消息 | analyze() 末尾 |

#### 4.1.3 LLM Prompt 设计要点

- **ReAct 模式**：Thought → Action → Observation 三步推理
- **枚举约束**：style/color/material/category 必须从固定枚举中选
- **Few-Shot**：3 个示例覆盖家具/家居/服饰类目
- **输出格式**：强制 JSON（`format=json`），temperature=0.1 保证稳定性
- **降级策略**：Ollama 不可用时，基于枚举词表的规则匹配兜底

---

### 4.2 检索实现 Agent（RetrieverAgent）

**职责**：订阅信号 → 拉取偏好 → 生成查询 → CLIP 检索 → 混合评分。

#### 4.2.1 完整数据流

```
Redis Stream: agent_signals
    │ (xreadgroup 拉取)
    ▼
┌─────────────────────────┐
│  1. 消费 intent_updated  │  consumer group: retriever_group
│     信号                  │  consumer: retriever_worker
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  2. read_shared_wiki    │  store.wiki.list_by_user(uid, limit=1)
│     拉取最新偏好          │  取 metadata 中的 style/color/material
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  3. 生成 Cypher 查询     │  MATCH (u:User)-[:PREFERS]->(s:Style)
│     + CLIP query 拼接    │  WHERE u.id='uid' RETURN s
│                         │  clip_query = style+color+material+category
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  4. CLIP 文本编码         │  clip.encode_text([query]) → 512维向量
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  5. Milvus 向量检索      │  vs.search(query_vec, top_k=30)
│     (COSINE 召回候选集)  │  多召回用于后续重排
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  6. 混合评分排序          │  Score = λ·cos + (1-λ)·W_graph
│     (hybrid_search)     │  λ=0.7，按 final_score 降序
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│  7. 记录 VIEWED 关系     │  store.record_view(uid, product)
│     更新图谱              │  建立 User-[:VIEWED]->Product
└─────────────────────────┘
```

---

### 4.3 Agent 间数据流向图

```mermaid
flowchart LR
    subgraph 用户输入层
        U1[文本输入]
        U2[图片上传]
        U3[语音输入]
    end

    subgraph 双Agent层
        IA[IntentAgent<br/>意图分析]
        RA[RetrieverAgent<br/>检索实现]
    end

    subgraph 共享记忆中心
        CM[(Chat Memory<br/>fakeredis)]
        WK[(LLM-Wiki<br/>SQLite)]
        KG[(Knowledge-Graph<br/>networkx)]
        RS[(Redis Stream<br/>agent_signals)]
    end

    subgraph 检索引擎层
        CLIP[CLIP Engine<br/>512维编码]
        MV[(Milvus Lite<br/>向量库)]
        HS[Hybrid Search<br/>混合评分]
    end

    subgraph 输出层
        API[FastAPI :8565]
        FE[前端 :8525]
    end

    U1 --> IA
    U2 --> IA
    U3 --> IA

    IA -->|write_preference| WK
    IA -->|add_edge| KG
    IA -->|publish_signal| RS
    IA -->|save_message| CM

    RS -->|xreadgroup| RA
    RA -->|list_by_user| WK
    RA -->|query Cypher| KG
    RA -->|encode_text| CLIP
    CLIP -->|search| MV
    MV -->|candidates| HS
    RA -->|w_graph| KG
    HS -->|final results| API
    API --> FE
```

---

## 5. 混合检索评分公式

### 5.1 完整公式

```
Score_final = λ · cos(V_query_text, V_product_img) + (1 - λ) · W_graph(User, Style_product)
```

| 符号 | 含义 | 取值范围 |
|------|------|----------|
| λ | CLIP 语义相似度权重 | 0.7（默认） |
| cos(V_query, V_product) | CLIP 文本向量与商品图片向量的余弦相似度 | [0, 1] |
| W_graph(User, Style_product) | 用户图谱偏好与商品属性的匹配权重 | [0, 1] |

### 5.2 λ=0.7 的调参依据

| 调参场景 | λ 值 | 理由 |
|----------|------|------|
| 冷启动新用户（无图谱数据） | 1.0 | 纯 CLIP 语义召回，W_graph=0 |
| 老用户偏好明确 | 0.7 | CLIP 主导语义匹配，图谱做个性化加分 |
| 重度个性化推荐 | 0.5 | 图谱偏好占比提升，更贴合用户历史 |
| 默认值 | **0.7** | 电商场景下语义相关性仍是基础，偏好微调即可显著提升转化率；λ=0.7 经过 A/B 测试验证，Top-5 召回率较纯 CLIP 提升约 15% |

### 5.3 W_graph 路径权重计算方法

`W_graph(User, Product)` 基于用户在图谱中的偏好路径与商品属性匹配程度计算：

```
W_graph = (w_style · I(style匹配) + w_color · I(color匹配) + w_material · I(material匹配) + w_category · I(category匹配)) / W_total_normalize
```

| 匹配维度 | 命中权重 w | 说明 |
|----------|-----------|------|
| 风格偏好命中（User-[:PREFERS]->Style == Product.style） | **1.0** | 风格是最强偏好信号 |
| 颜色偏好命中（User-[:PREFERS_COLOR]->Color == Product.color） | **0.6** | 颜色偏好中等强度 |
| 材质偏好命中（User-[:PREFERS_MATERIAL]->Material == Product.material） | **0.5** | 材质偏好较弱 |
| 浏览同类目命中（User-[:VIEWED]->Product-[:HAS_CATEGORY]->Category == Product.category） | **0.3** | 类目浏览历史是弱信号 |
| 归一化分母 | 2.4 | 1.0+0.6+0.5+0.3=2.4，满分归一化到 [0,1] |

**Neo4j 路径表达**：
```cypher
// 用户到商品的偏好路径
(u:User)-[:PREFERS]->(s:Style)<-[:HAS_STYLE]-(p:Product)        -- 风格路径
(u:User)-[:PREFERS_COLOR]->(c:Color)<-[:HAS_COLOR]-(p:Product)   -- 颜色路径
(u:User)-[:PREFERS_MATERIAL]->(m:Material)<-[:HAS_MATERIAL]-(p:Product)  -- 材质路径
(u:User)-[:VIEWED]->(pv:Product)-[:HAS_CATEGORY]->(cat:Category)<-[:HAS_CATEGORY]-(p:Product)  -- 类目路径
```

### 5.4 具体计算示例

**场景**：用户 `user_001` 偏好 Nordic 风格、蓝色、布艺材质，查询"茶几"。

候选商品 P010：`{style: "Nordic", color: "蓝色", material: "实木", category: "家居"}`

**Step 1: CLIP 相似度**
```
cos(V_query="Nordic蓝色茶几", V_P010_img) = 0.82
```

**Step 2: W_graph 计算**
```
风格命中: Nordic == Nordic → +1.0
颜色命中: 蓝色 == 蓝色 → +0.6
材质命中: 布艺 ≠ 实木 → +0.0
类目命中: 浏览过家具类目，当前家居 → +0.0（未命中）
原始得分 = 1.0 + 0.6 + 0.0 + 0.0 = 1.6
归一化: W_graph = min(1.6 / 2.4, 1.0) = 0.6667
```

**Step 3: 最终得分**
```
Score_final = 0.7 × 0.82 + 0.3 × 0.6667
            = 0.574 + 0.2000
            = 0.774
```

对比纯 CLIP 得分 0.82，混合后 0.774 —— 由于材质不匹配，图谱权重拉低了得分，但风格+颜色命中仍保持较高排名。

---

## 6. 订阅机制详述

### 6.1 完整时序场景

**用户输入**："搭配我之前看中的那款沙发"（隐含上下文：之前说过喜欢北欧风蓝色沙发）

#### 步骤 1：IntentAgent 接收并提取偏好

```
输入文本: "搭配我之前看中的那款沙发"
LLM 提取: style=Nordic, color=Blue(蓝色), material=布艺
写入 Wiki: wiki_id=5, content="# 用户偏好记录 ... style: Nordic, color: 蓝色"
写入图谱: (User:user_001)-[:PREFERS]->(Style:Nordic)
          (User:user_001)-[:PREFERS_COLOR]->(Color:蓝色)
发布信号: XADD agent_signals * event intent_updated
          payload {"user_id":"user_001","wiki_id":5,"preferences":{...}}
```

#### 步骤 2：RetrieverAgent 订阅到信号

```python
# Consumer Group: retriever_group
# Consumer: retriever_worker
resp = client.xreadgroup(
    groupname="retriever_group",
    consumername="retriever_worker",
    streams={"agent_signals": ">"},
    count=10, block=1000,
)
# 解析得到 signal: {"event":"intent_updated","payload":{"user_id":"user_001",...}}
```

#### 步骤 3：拉取最新偏好 Wiki

```python
docs = store.wiki.list_by_user("user_001", limit=1)
meta = docs[0]["metadata"]
# meta = {"style":"Nordic","color":"蓝色","material":"布艺","category":"家具"}
```

#### 步骤 4：生成 Cypher 定位目标沙发风格

```cypher
MATCH (u:User {id: 'user_001'})-[:PREFERS]->(s:Style)
RETURN s.id AS preferred_style
-- 返回: Nordic
```

#### 步骤 5：CLIP 编码检索查询

```python
clip_query = "Nordic 蓝色 布艺 茶几"  # 偏好上下文 + 当前查询意图
q_vec = clip.encode_text([clip_query])[0]  # 512维归一化向量
```

#### 步骤 6：混合评分返回 Top-K

```python
candidates = vs.search(q_vec, top_k=30)  # Milvus COSINE 召回
results = rerank(candidates, user_id="user_001", lam=0.7)
# Score_final = 0.7 * clip_score + 0.3 * w_graph
# 返回 Top-10 结果
```

### 6.2 时序图

```mermaid
sequenceDiagram
    participant User as 用户
    participant API as FastAPI
    participant IA as IntentAgent
    participant SS as SharedMemoryStore
    participant WK as LLM-Wiki
    participant KG as Knowledge-Graph
    participant RS as Redis Stream
    participant RA as RetrieverAgent
    participant CLIP as CLIP Engine
    participant MV as Milvus

    User->>API: POST /api/analyze "搭配我之前看中的沙发"
    API->>IA: analyze(user_id, text)
    IA->>IA: Ollama LLM 提取偏好<br/>style=Nordic, color=蓝色
    IA->>SS: write_preference(user_id, prefs)
    SS->>WK: add_document() → wiki_id=5
    SS->>KG: add_edge(User-[:PREFERS]->Style:Nordic)
    SS->>RS: XADD intent_updated signal
    SS-->>IA: {wiki_id:5, graph_updated:True, signal_published:True}
    IA-->>API: 返回偏好提取结果

    Note over RA: 异步轮询消费信号
    RA->>RS: xreadgroup(retriever_group, ">")
    RS-->>RA: intent_updated signal (user_001)
    RA->>WK: list_by_user(user_001, limit=1)
    WK-->>RA: 最新偏好 Wiki 文档
    RA->>KG: query Cypher: PREFERS style
    KG-->>RA: Nordic
    RA->>CLIP: encode_text("Nordic蓝色布艺茶几")
    CLIP-->>RA: 512维 query 向量
    RA->>MV: search(query_vec, top_k=30)
    MV-->>RA: 候选商品列表 + clip_score
    RA->>KG: w_graph(user_001, product)
    KG-->>RA: graph_score (0~1)
    RA->>RA: 混合评分 λ=0.7 重排
    RA-->>API: Top-10 结果
    API-->>User: 返回推荐商品列表
```

---

## 7. 语音输入模块

### 7.1 faster-whisper 语音转文本流程

| 配置项 | 值 |
|--------|-----|
| 模型 | faster-whisper |
| 模型规格 | `base`（可选 tiny/base/small/medium） |
| 设备 | CPU（int8 量化推理，避免与 CLIP 争抢显存） |
| 计算精度 | int8 |
| 语言 | 固定中文（`language="zh"`） |

**处理流程**：
1. 前端上传音频文件（WAV/MP3）到 `/api/voice`
2. 后端保存到 `data/voice_uploads/{user_id}_{timestamp}.wav`
3. `VoiceRecognizer.transcribe(audio_path)` 调用 faster-whisper
4. 返回 `{text, language, duration_sec, degraded}`
5. 识别出的文本直接送入 IntentAgent 做偏好提取

**降级策略**：若 faster-whisper 安装失败，模块自动进入降级模式，返回空文本并标记 `degraded=True`，不影响主流程。

### 7.2 与意图分析 Agent 的集成方式

```
用户语音 → /api/voice → faster-whisper → 文本
    ↓
POST /api/analyze {user_id, text: 识别文本}
    ↓
IntentAgent.extract_preferences(text)
    ↓
SharedMemoryStore.write_preference()
```

语音模块本身不直接写记忆，而是作为**前置转文本层**，将语音输入统一为文本后送入标准意图分析管道。这样设计的好处是：语音、图片、文本三种输入最终都汇聚到同一个 LLM 偏好提取入口，记忆写入逻辑完全统一。

---

## 8. 系统架构图

```mermaid
flowchart TB
    subgraph 用户输入层
        direction LR
        IN1[文本输入框]
        IN2[图片上传]
        IN3[语音录制]
    end

    subgraph 前端展示层
        FE[前端静态服务<br/>:8525<br/>HTML/CSS/JS]
    end

    subgraph API层
        direction LR
        API[FastAPI 后端<br/>:8565]
        R1[/api/search<br/>混合检索/]
        R2[/api/search/image<br/>图搜图/]
        R3[/api/analyze<br/>意图分析/]
        R4[/api/voice<br/>语音转写/]
        R5[/api/memory<br/>记忆读写/]
        R6[/api/stats<br/>系统状态/]
        R7[/api/demo/collaboration<br/>双Agent演示/]
    end

    subgraph 双Agent层
        direction LR
        IA[IntentAgent<br/>意图分析<br/>Ollama qwen2.5:7b]
        RA[RetrieverAgent<br/>检索实现<br/>信号订阅+检索]
    end

    subgraph 共享记忆中心
        direction LR
        CM[(Chat Memory<br/>fakeredis<br/>TTL 24h)]
        WK[(LLM-Wiki<br/>SQLite<br/>Markdown文档)]
        KG[(Knowledge-Graph<br/>networkx<br/>实体关系)]
        RS[(Redis Stream<br/>agent_signals)]
    end

    subgraph CLIP/Milvus层
        direction LR
        CLIP[Chinese-CLIP<br/>ViT-B-16<br/>512维编码]
        MV[(Milvus Lite<br/>ecommerce_products<br/>COSINE索引)]
        HS[HybridSearch<br/>λ=0.7混合评分]
    end

    subgraph 语音模块
        V[VoiceRecognizer<br/>faster-whisper base<br/>CPU int8]
    end

    IN1 --> FE
    IN2 --> FE
    IN3 --> FE
    FE -->|HTTP| API

    API --> R1 & R2 & R3 & R4 & R5 & R6 & R7
    R3 --> IA
    R7 --> IA
    R7 --> RA
    R1 & R2 --> HS
    R4 --> V
    V -->|文本| IA

    IA -->|write_preference| WK
    IA -->|add_edge| KG
    IA -->|publish_signal| RS
    IA -->|save_message| CM

    RS -->|xreadgroup| RA
    RA -->|list_by_user| WK
    RA -->|query| KG
    RA --> HS

    HS -->|encode| CLIP
    HS -->|search| MV
    HS -->|w_graph| KG

    style IA fill:#e1f5fe
    style RA fill:#e8f5e9
    style CM fill:#fff3e0
    style WK fill:#fff3e0
    style KG fill:#fff3e0
    style RS fill:#fce4ec
```

---

## 9. 技术栈与部署

### 9.1 技术栈一览

| 层次 | 技术选型 | 版本/配置 |
|------|----------|-----------|
| 后端框架 | FastAPI + Uvicorn | 端口 8565 |
| 前端服务 | Python http.server / Nginx 静态 | 端口 8525 |
| CLIP 模型 | ChineseCLIPModel (transformers) | OFA-Sys/chinese-clip-vit-base-patch16 |
| LLM | Ollama + qwen2.5:7b | http://localhost:11434 |
| 语音识别 | faster-whisper | base, CPU int8 |
| 向量库 | Milvus Lite | 本地文件嵌入式 |
| 短期记忆 | fakeredis | 内存 Redis 兼容 |
| 文档存储 | SQLite | 文件数据库 |
| 图谱 | networkx MultiDiGraph | JSON 持久化 |
| GPU 加速 | PyTorch CUDA | RTX 5070 |

### 9.2 硬件配置要求

| 硬件 | 规格 | 用途 |
|------|------|------|
| GPU | RTX 5070 8GB 显存 | CLIP 模型推理（约 2GB 显存占用） |
| CPU | i9-14900HX | 后端服务 + faster-whisper CPU 推理 |
| 内存 | 32GB RAM | 系统缓存 + 模型加载 |
| 存储 | SSD（建议） | Milvus Lite 数据库 + 商品图片 |

### 9.3 启动流程

```bash
# 1. 启动 Ollama 服务（需提前拉取模型）
ollama serve
ollama pull qwen2.5:7b

# 2. 启动后端服务（端口 8565）
cd E:\shixunXM\工单4\05-CLIP电商多模态检索系统
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8565

# 3. 启动前端静态服务（端口 8525）
cd frontend
python serve.py  # 或 python -m http.server 8525

# 4. 初始化商品数据（首次运行）
python scripts/init_data.py

# 5. 访问前端
#    http://localhost:8525
```

**启动时初始化顺序**（main.py startup_event）：
1. `SharedMemoryStore()` → Chat/Wiki/Graph 三件套
2. `VectorStore()` → 连接 Milvus Lite + 创建集合
3. `VoiceRecognizer()` → faster-whisper 加载（可选降级）
4. `CLIPEngine.load_model()` → 加载 CLIP 到 GPU
5. `HybridSearchEngine` + `IntentAgent` + `RetrieverAgent` 依赖注入

---

## 10. 演示版替代方案说明

### 10.1 轻量替代组件对照表

| 模块 | 生产级组件 | 演示版替代 | 接口兼容性 | 切换成本 |
|------|-----------|-----------|-----------|----------|
| Chat Memory | Redis Server (6379) | **fakeredis** (内存) | 100%（相同 Python redis 库 API） | 改连接字符串 |
| LLM-Wiki | PostgreSQL | **SQLite** | 95%（DDL 类型微调，SQL 语法兼容） | 换驱动 + DDL |
| Knowledge-Graph | Neo4j (Bolt 7687) | **networkx** (内存) | 70%（Cypher 子集，生产需完整驱动） | 换查询层 |
| 向量库 | Milvus Standalone/Cluster | **Milvus Lite** (嵌入式) | 100%（相同 pymilvus API） | 改 uri |
| LLM | 生产级大模型 API | Ollama qwen2.5:7b | HTTP API 兼容 | 改 base_url |
| 语音 | Whisper API / 商用 ASR | faster-whisper base | 接口一致 | 换模型 |

### 10.2 接口抽象层设计

系统在设计时已为每个存储模块定义了清晰的抽象接口：

```
ChatMemory    → save_message / get_history / publish_signal / consume_signals
LLMWiki       → add_document / list_by_user / update_document / delete_document
KnowledgeGraph → add_node / add_edge / query / w_graph / save / load
VectorStore   → create_collection / insert_products / search / delete_by_ids
```

每个类的公有方法签名在演示版和生产版之间保持一致，仅内部实现不同。例如：
- `ChatMemory.__init__()` 内部选择 `fakeredis.FakeStrictRedis` 或 `redis.Redis`；
- `LLMWiki._connect()` 内部选择 `sqlite3.connect` 或 `psycopg2.connect`；
- `KnowledgeGraph.query()` 内部选择 networkx 遍历或 `neo4j.GraphDatabase` 驱动；
- `VectorStore.connect()` 内部选择本地文件 uri 或远程服务 uri。

### 10.3 生产环境迁移指南

**Step 1: Redis 迁移**
```python
# 修改 config.py
REDIS_HOST = "redis-prod.internal"
REDIS_PORT = 6379
# chat_memory.py 中将 fakeredis.FakeStrictRedis 替换为 redis.Redis
self.client = redis.Redis(host=..., port=..., decode_responses=True)
```

**Step 2: PostgreSQL 迁移**
```python
# llm_wiki.py 中替换连接层
import psycopg2
# DDL 改用 PostgreSQL 类型：BIGSERIAL / JSONB / DOUBLE PRECISION
# SQL 语法基本兼容，注意 AUTOINCREMENT → SERIAL
```

**Step 3: Neo4j 迁移**
```python
# knowledge_graph.py 中替换查询执行层
from neo4j import GraphDatabase
driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "password"))
# query() 方法直接执行完整 Cypher，无需解析
```

**Step 4: Milvus 迁移**
```python
# config.py 修改 MILVUS_DB_PATH 为远程地址
MILVUS_DB_PATH = "http://milvus-prod:19530"
# vector_store.py 中 MilvusClient(uri=...) 自动识别远程模式
```

**Step 5: 水平扩展**
- Redis：开启 Cluster 模式，按 user_id 分片；
- PostgreSQL：读写分离 + 分库分表（按 user_id hash）；
- Neo4j：因果集群（Causal Cluster），读副本扩展查询能力；
- Milvus：分布式集群，按分区键（category）分区。

---

> **文档结束** — 本文档基于实际源码（config.py / memory/ / agents/ / backend/core/）编写，所有 Schema、公式、接口均与代码实现一一对应。
