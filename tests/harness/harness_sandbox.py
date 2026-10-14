# -*- coding: utf-8 -*-
"""
Agent Harness 测试沙箱
======================

职责:
    1. 模拟用户输入流，拦截双 Agent (IntentAgent / RetrieverAgent) 的工具调用行为。
    2. 记录完整 Execution Trajectory (决策轨迹)，供断言与复盘。
    3. 提供 TrajectoryValidator 验证工具调用序列是否符合工单约定。

设计要点:
    - 使用独立的临时 SQLite DB (避免污染生产 data/llm_wiki.db)。
    - 使用内存 fakeredis (每个沙箱实例独立 Stream)，不依赖外部 Redis。
    - 通过 monkey-patch 拦截:
        * IntentAgent.extract_preferences          -> IntentAgent.Extract_Features
        * SharedMemoryStore.wiki.add_document      -> IntentAgent.Write_Wiki
        * SharedMemoryStore.chat.consume_signals  -> RetrieverAgent.Subscribe_Signal
        * SharedMemoryStore.wiki.list_by_user     -> RetrieverAgent.Read_Wiki
        * HybridSearchEngine.search_by_text       -> RetrieverAgent.vector_Search
    - HybridSearchEngine 用 MockEngine 替代，避免在测试阶段重复加载 CLIP/GPU。
"""
from __future__ import annotations

import os
import sys
import json
import time
import uuid
import logging
import threading
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 让测试脚本可以直接 import 项目根目录模块
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402
from memory.shared_store import SharedMemoryStore  # noqa: E402
from agents.intent_agent import IntentAgent  # noqa: E402
from agents.retriever_agent import RetrieverAgent  # noqa: E402


# ---------------------------------------------------------------------------
# 工具名常量 (工单约定)
# ---------------------------------------------------------------------------
TOOL_EXTRACT_FEATURES = "IntentAgent.Extract_Features"
TOOL_WRITE_WIKI       = "IntentAgent.Write_Wiki"
TOOL_SUBSCRIBE_SIGNAL = "RetrieverAgent.Subscribe_Signal"
TOOL_READ_WIKI        = "RetrieverAgent.Read_Wiki"
TOOL_VECTOR_SEARCH    = "RetrieverAgent.vector_Search"

# 工单要求的标准工具调用序列
EXPECTED_TOOL_SEQUENCE: List[str] = [
    TOOL_EXTRACT_FEATURES,
    TOOL_WRITE_WIKI,
    TOOL_SUBSCRIBE_SIGNAL,
    TOOL_READ_WIKI,
    TOOL_VECTOR_SEARCH,
]


# ---------------------------------------------------------------------------
# Mock HybridEngine: 不加载 CLIP，仅返回伪造召回结果，用于轨迹/保真度测试
# ---------------------------------------------------------------------------
class MockHybridEngine:
    """模拟混合检索引擎，避免测试阶段重复加载 CLIP/GPU。"""

    def __init__(self, search_latency_ms: float = 5.0) -> None:
        self.search_latency_ms = search_latency_ms
        # 记录最近一次被检索的 query (供上下文保真度断言)
        self.last_query: str = ""
        self.call_count: int = 0

    def search_by_text(self, query: str,
                       user_id: Optional[str] = None,
                       mode: str = "hybrid",
                       top_k: int = 10,
                       lam: Optional[float] = None) -> Dict[str, Any]:
        self.last_query = query
        self.call_count += 1
        # 返回 3 条伪造商品结果，字段与真实引擎对齐
        fake_results = [
            {"product_id": f"P{100+i}", "title": f"测试商品-{i}",
             "price": 999.0 + i, "category": "家具", "style": "Nordic",
             "color": "蓝色", "material": "布艺",
             "clip_score": 0.85 - i * 0.05, "graph_score": 0.5,
             "final_score": 0.7 - i * 0.04}
            for i in range(3)
        ]
        return {
            "query_embedding": [0.0] * 8,
            "results": fake_results,
            "latency_ms": self.search_latency_ms,
        }


# ---------------------------------------------------------------------------
# 轨迹数据结构
# ---------------------------------------------------------------------------
@dataclass
class TrajectoryStep:
    """单条工具调用记录。"""
    seq: int                  # 自增序号
    agent: str                # intent_agent / retriever_agent / harness
    tool: str                 # 工具名 (见上方常量)
    input_summary: Dict[str, Any] = field(default_factory=dict)
    output_summary: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    thread_id: int = field(default_factory=lambda: threading.get_ident())


class Trajectory:
    """一次完整协同过程的决策轨迹容器。"""

    def __init__(self, run_id: Optional[str] = None) -> None:
        self.run_id: str = run_id or f"run_{uuid.uuid4().hex[:8]}"
        self.steps: List[TrajectoryStep] = []
        self._lock = threading.Lock()

    def add(self, agent: str, tool: str,
            input_summary: Optional[Dict[str, Any]] = None,
            output_summary: Optional[Dict[str, Any]] = None) -> TrajectoryStep:
        with self._lock:
            step = TrajectoryStep(
                seq=len(self.steps) + 1,
                agent=agent,
                tool=tool,
                input_summary=input_summary or {},
                output_summary=output_summary or {},
            )
            self.steps.append(step)
        return step

    def tool_sequence(self) -> List[str]:
        """按时间顺序返回工具名列表。"""
        return [s.tool for s in self.steps]

    def find(self, tool: str) -> List[TrajectoryStep]:
        return [s for s in self.steps if s.tool == tool]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_count": len(self.steps),
            "steps": [asdict(s) for s in self.steps],
        }


# ---------------------------------------------------------------------------
# 轨迹验证器
# ---------------------------------------------------------------------------
class TrajectoryValidator:
    """对 Execution Trajectory 做序列与上下文断言。"""

    @staticmethod
    def assert_strict_sequence(traj: Trajectory,
                               expected: Optional[List[str]] = None) -> None:
        """断言轨迹中的工具调用严格等于 expected 序列。"""
        expected = expected or EXPECTED_TOOL_SEQUENCE
        actual = traj.tool_sequence()
        if actual != expected:
            raise AssertionError(
                f"工具调用序列不匹配!\n  期望: {expected}\n  实际: {actual}"
            )

    @staticmethod
    def assert_prefix(traj: Trajectory, prefix: List[str]) -> None:
        """断言轨迹以 prefix 开头 (允许后续有额外步骤)。"""
        actual = traj.tool_sequence()
        if actual[:len(prefix)] != prefix:
            raise AssertionError(
                f"工具调用前缀不匹配!\n  期望前缀: {prefix}\n  实际前N步: {actual[:len(prefix)]}"
            )

    @staticmethod
    def assert_order(traj: Trajectory, earlier: str, later: str) -> None:
        """断言 earlier 工具在 later 之前调用。"""
        seq = traj.tool_sequence()
        try:
            i_earlier = seq.index(earlier)
            i_later = seq.index(later)
        except ValueError as e:
            raise AssertionError(f"轨迹中缺少工具: {e}")
        if i_earlier >= i_later:
            raise AssertionError(
                f"顺序错误: {earlier}(idx={i_earlier}) 必须在 "
                f"{later}(idx={i_later}) 之前"
            )


# ---------------------------------------------------------------------------
# 沙箱主体
# ---------------------------------------------------------------------------
class HarnessSandbox:
    """Agent Harness 测试沙箱。

    用法:
        sb = HarnessSandbox()
        sb.bootstrap()           # 初始化 store/agent 并打桩
        sb.run_user_turn("搭配我周一上传的那款蓝色沙发", user_id="u_test")
        traj = sb.trajectory
        TrajectoryValidator.assert_strict_sequence(traj)
        sb.teardown()
    """

    def __init__(self,
                 temp_db_path: Optional[str] = None,
                 graph_path: Optional[str] = None) -> None:
        # 使用临时 SQLite DB，避免污染生产 data/llm_wiki.db
        self._tmp_dir = tempfile.mkdtemp(prefix="harness_")
        self.db_path = temp_db_path or os.path.join(self._tmp_dir, "harness_wiki.db")
        self.graph_path = graph_path or os.path.join(self._tmp_dir, "harness_graph.json")

        # 运行期对象
        self.store: Optional[SharedMemoryStore] = None
        self.intent_agent: Optional[IntentAgent] = None
        self.retriever_agent: Optional[RetrieverAgent] = None
        self.engine: Optional[MockHybridEngine] = None
        self.trajectory = Trajectory()

        # 用于恢复 monkey-patch 的原始方法引用
        self._originals: Dict[str, Any] = {}
        self._patched = False

    # ------------------------------------------------------------------ #
    # 初始化与打桩
    # ------------------------------------------------------------------ #
    def bootstrap(self) -> None:
        """初始化共享记忆库与双 Agent，并打桩拦截工具调用。"""
        # 让 LLMWiki 使用临时 DB
        config.SQLITE_DB_PATH = self.db_path
        config.GRAPH_DB_PATH = self.graph_path

        self.store = SharedMemoryStore()
        self.engine = MockHybridEngine()
        self.intent_agent = IntentAgent(shared_store=self.store)
        self.retriever_agent = RetrieverAgent(
            shared_store=self.store, hybrid_engine=self.engine
        )

        # 关闭真实 Ollama 调用，强制走规则降级提取，保证测试确定性
        self.intent_agent._call_ollama = lambda prompt: None  # type: ignore

        self._patch_tool_calls()
        self._patched = True

    def _patch_tool_calls(self) -> None:
        """Monkey-patch 关键方法，把每次调用写入 trajectory。"""
        store = self.store
        traj = self.trajectory
        intent = self.intent_agent
        retriever = self.retriever_agent
        engine = self.engine

        # -------- IntentAgent.Extract_Features --------
        orig_extract = intent.extract_preferences
        self._originals["extract_preferences"] = orig_extract

        def patched_extract(text: str) -> Dict[str, Any]:
            prefs = orig_extract(text)
            traj.add(
                agent="intent_agent",
                tool=TOOL_EXTRACT_FEATURES,
                input_summary={"text": text},
                output_summary={"preferences": prefs},
            )
            return prefs
        intent.extract_preferences = patched_extract  # type: ignore

        # -------- IntentAgent.Write_Wiki --------
        orig_add_document = store.wiki.add_document
        self._originals["wiki_add_document"] = orig_add_document

        def patched_add_document(user_id, title, content, metadata=None):
            wiki_id = orig_add_document(user_id, title, content, metadata)
            traj.add(
                agent="intent_agent",
                tool=TOOL_WRITE_WIKI,
                input_summary={"user_id": user_id, "title": title,
                               "metadata": metadata},
                output_summary={"wiki_id": wiki_id},
            )
            return wiki_id
        store.wiki.add_document = patched_add_document  # type: ignore

        # -------- RetrieverAgent.Subscribe_Signal --------
        orig_consume = store.chat.consume_signals
        self._originals["consume_signals"] = orig_consume

        def patched_consume(consumer_name="retriever_worker", count=10, block_ms=1000):
            signals = orig_consume(consumer_name=consumer_name,
                                   count=count, block_ms=block_ms)
            traj.add(
                agent="retriever_agent",
                tool=TOOL_SUBSCRIBE_SIGNAL,
                input_summary={"consumer": consumer_name, "count": count},
                output_summary={"signal_count": len(signals)},
            )
            return signals
        store.chat.consume_signals = patched_consume  # type: ignore

        # -------- RetrieverAgent.Read_Wiki --------
        orig_list = store.wiki.list_by_user
        self._originals["wiki_list_by_user"] = orig_list

        def patched_list_by_user(user_id, limit=50):
            docs = orig_list(user_id, limit)
            traj.add(
                agent="retriever_agent",
                tool=TOOL_READ_WIKI,
                input_summary={"user_id": user_id, "limit": limit},
                output_summary={"doc_count": len(docs),
                                 "metadata": docs[0].get("metadata") if docs else {}},
            )
            return docs
        store.wiki.list_by_user = patched_list_by_user  # type: ignore

        # -------- RetrieverAgent.vector_Search --------
        orig_search = engine.search_by_text
        self._originals["engine_search_by_text"] = orig_search

        def patched_search(query, user_id=None, mode="hybrid",
                           top_k=10, lam=None):
            result = orig_search(query=query, user_id=user_id,
                                 mode=mode, top_k=top_k, lam=lam)
            traj.add(
                agent="retriever_agent",
                tool=TOOL_VECTOR_SEARCH,
                input_summary={"query": query, "user_id": user_id, "mode": mode},
                output_summary={"result_count": len(result.get("results", []))},
            )
            return result
        engine.search_by_text = patched_search  # type: ignore

    # ------------------------------------------------------------------ #
    # 业务流: 模拟一次完整双 Agent 协同
    # ------------------------------------------------------------------ #
    def run_user_turn(self, user_text: str,
                      user_id: str = "u_harness",
                      session_id: Optional[str] = None) -> Dict[str, Any]:
        """执行一次完整协同: 意图Agent写记忆 -> 检索Agent订阅信号 -> 读Wiki -> 向量检索。"""
        assert self._patched, "请先调用 bootstrap()"
        # Step 1: IntentAgent 分析用户输入 (内部会触发 Extract_Features + Write_Wiki)
        intent_out = self.intent_agent.analyze(
            user_id=user_id, text=user_text, session_id=session_id
        )

        # Step 2: RetrieverAgent 订阅信号 (触发 Subscribe_Signal)
        signals = self.retriever_agent.poll_signals(consumer=f"worker_{user_id}")

        # Step 3: 处理信号 -> 读 Wiki -> 向量检索 (触发 Read_Wiki + vector_Search)
        handle_out = None
        for sig in signals:
            handle_out = self.retriever_agent.handle_signal(sig)
            if handle_out is not None:
                break

        return {
            "intent_output": intent_out,
            "signals": signals,
            "retriever_output": handle_out,
        }

    # ------------------------------------------------------------------ #
    # 清理
    # ------------------------------------------------------------------ #
    def teardown(self) -> None:
        """清理临时文件。"""
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            # SQLite 可能生成 -wal / -shm
            for suffix in ("-wal", "-shm"):
                p = self.db_path + suffix
                if os.path.exists(p):
                    os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 便捷上下文管理器
# ---------------------------------------------------------------------------
@contextmanager
def harness_context(**kwargs) -> Any:
    sb = HarnessSandbox(**kwargs)
    sb.bootstrap()
    try:
        yield sb
    finally:
        sb.teardown()


# ---------------------------------------------------------------------------
# CLI 自检
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with harness_context() as sb:
        out = sb.run_user_turn("搭配我周一上传的那款蓝色沙发")
        print("=" * 60)
        print("轨迹:")
        for step in sb.trajectory.steps:
            print(f"  [{step.seq}] {step.tool}")
        print("=" * 60)
        TrajectoryValidator.assert_strict_sequence(sb.trajectory)
        print("[OK] 工具调用序列符合工单约定!")
        print(json.dumps(out["intent_output"], ensure_ascii=False, indent=2))
