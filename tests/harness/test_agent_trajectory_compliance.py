# -*- coding: utf-8 -*-
"""
轨迹一致性测试 (Agent Trajectory Compliance)
=============================================

工单要求:
    双 Agent 的 Tool 调用序列必须严格满足:
        [IntentAgent.Extract_Features]
            -> [IntentAgent.Write_Wiki]
            -> [RetrieverAgent.Subscribe_Signal]
            -> [RetrieverAgent.Read_Wiki]
            -> [RetrieverAgent.vector_Search]

本测试:
    1. 模拟用户输入 "搭配我周一上传的那款蓝色沙发"。
    2. 断言 IntentAgent 在所有写操作中优先执行 write_shared_wiki。
    3. 断言 RetrieverAgent 在 query_milvus (vector_Search) 之前已执行 read_shared_wiki。
"""
import os
import sys

import pytest

# 让 pytest 可以 import 本目录的沙箱模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from harness_sandbox import (  # noqa: E402
    HarnessSandbox,
    TrajectoryValidator,
    EXPECTED_TOOL_SEQUENCE,
    TOOL_EXTRACT_FEATURES,
    TOOL_WRITE_WIKI,
    TOOL_SUBSCRIBE_SIGNAL,
    TOOL_READ_WIKI,
    TOOL_VECTOR_SEARCH,
)


# ---------------------------------------------------------------------------
# Fixture: 每个测试用例独立沙箱 (独立 SQLite DB / Stream)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def sandbox():
    sb = HarnessSandbox()
    sb.bootstrap()
    yield sb
    sb.teardown()


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_tool_call_sequence_strict_compliance(sandbox: HarnessSandbox):
    """断言双 Agent 的 Tool 调用序列严格等于工单约定。"""
    # 模拟用户输入: 指代消解场景 (周一上传的那款蓝色沙发)
    sandbox.run_user_turn(
        user_text="搭配我周一上传的那款蓝色沙发",
        user_id="u_trajectory",
    )
    seq = sandbox.trajectory.tool_sequence()
    print("实际轨迹序列:", seq)
    # 严格序列断言
    TrajectoryValidator.assert_strict_sequence(sandbox.trajectory, EXPECTED_TOOL_SEQUENCE)


def test_intent_agent_write_wiki_before_retriever_subscribe(sandbox: HarnessSandbox):
    """断言 IntentAgent 的 Write_Wiki 发生在 RetrieverAgent 的 Subscribe_Signal 之前。"""
    sandbox.run_user_turn(
        user_text="搭配我周一上传的那款蓝色沙发",
        user_id="u_order1",
    )
    # Write_Wiki 必须在 Subscribe_Signal 之前
    TrajectoryValidator.assert_order(sandbox.trajectory,
                                     TOOL_WRITE_WIKI, TOOL_SUBSCRIBE_SIGNAL)
    # Extract_Features 必须在 Write_Wiki 之前
    TrajectoryValidator.assert_order(sandbox.trajectory,
                                     TOOL_EXTRACT_FEATURES, TOOL_WRITE_WIKI)


def test_retriever_read_wiki_before_vector_search(sandbox: HarnessSandbox):
    """断言 RetrieverAgent 在 query_milvus (vector_Search) 之前已执行 read_shared_wiki。"""
    sandbox.run_user_turn(
        user_text="搭配我周一上传的那款蓝色沙发",
        user_id="u_order2",
    )
    # Read_Wiki 必须在 vector_Search 之前
    TrajectoryValidator.assert_order(sandbox.trajectory,
                                     TOOL_READ_WIKI, TOOL_VECTOR_SEARCH)
    # Subscribe_Signal 必须在 Read_Wiki 之前 (先订阅到信号才会去读 Wiki)
    TrajectoryValidator.assert_order(sandbox.trajectory,
                                     TOOL_SUBSCRIBE_SIGNAL, TOOL_READ_WIKI)


def test_intent_agent_prioritizes_write_shared_wiki(sandbox: HarnessSandbox):
    """验证 IntentAgent 优先执行 write_shared_wiki 动作。

    在 IntentAgent 产生的所有轨迹步骤中，Write_Wiki 必须排在第一位
    (即 Extract_Features 之后立刻落库，不能先 publish_signal 再写库)。
    """
    sandbox.run_user_turn(
        user_text="搭配我周一上传的那款蓝色沙发",
        user_id="u_priority",
    )
    # 过滤出 intent_agent 的步骤
    intent_steps = [s for s in sandbox.trajectory.steps if s.agent == "intent_agent"]
    # intent_agent 必须至少产生 Extract_Features + Write_Wiki 两步
    assert len(intent_steps) >= 2, \
        f"IntentAgent 轨迹步骤不足: {intent_steps}"
    # 第一步必须是 Extract_Features
    assert intent_steps[0].tool == TOOL_EXTRACT_FEATURES, \
        f"IntentAgent 第一步必须是 Extract_Features, 实际: {intent_steps[0].tool}"
    # 第二步必须是 Write_Wiki (优先落库)
    assert intent_steps[1].tool == TOOL_WRITE_WIKI, \
        f"IntentAgent 第二步必须优先 Write_Wiki, 实际: {intent_steps[1].tool}"


def test_vector_search_called_after_wiki_read(sandbox: HarnessSandbox):
    """验证 RetrieverAgent 调用 query_milvus 之前已成功读到 Wiki (非空文档)。"""
    sandbox.run_user_turn(
        user_text="搭配我周一上传的那款蓝色沙发",
        user_id="u_fidelity",
    )
    # 找到 Read_Wiki 那一步的输出
    read_steps = sandbox.trajectory.find(TOOL_READ_WIKI)
    assert read_steps, "轨迹中缺少 Read_Wiki 步骤"
    # 必须读到至少 1 篇 Wiki 文档
    assert read_steps[-1].output_summary.get("doc_count", 0) >= 1, \
        "RetrieverAgent 在 vector_Search 之前没有读到任何 Wiki 文档"
    # 向量检索那一步的输入 query 必须非空 (否则说明没融合 Wiki 内容)
    search_steps = sandbox.trajectory.find(TOOL_VECTOR_SEARCH)
    assert search_steps, "轨迹中缺少 vector_Search 步骤"
    query = search_steps[-1].input_summary.get("query", "")
    assert query.strip() != "", "vector_Search 的 query 为空, 未融合 Wiki 偏好"
