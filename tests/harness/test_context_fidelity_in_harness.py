# -*- coding: utf-8 -*-
"""
信息保真度测试 (Context Fidelity in Harness)
==============================================

工单要求:
    断言 RetrieverAgent 最终用于 CLIP 检索的 Query 中，
    完全融合了 IntentAgent 写入共享 Wiki 的所有实体特征
    (颜色 / 材质 / 风格)，信息丢失率必须 = 0%。

方法:
    1. IntentAgent 从用户文本中提取 preferences dict。
    2. 对比 IntentAgent 写入的 preferences 与 RetrieverAgent 从 Wiki 读到的 metadata。
    3. 对比 Wiki metadata 与最终 CLIP query 字符串，统计未被融合的特征数。
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from harness_sandbox import (  # noqa: E402
    HarnessSandbox,
    TOOL_WRITE_WIKI,
    TOOL_READ_WIKI,
    TOOL_VECTOR_SEARCH,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def sandbox():
    sb = HarnessSandbox()
    sb.bootstrap()
    yield sb
    sb.teardown()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _extract_written_preferences(sb: HarnessSandbox) -> dict:
    """从轨迹中提取 IntentAgent 写入 Wiki 的 preferences metadata。"""
    steps = sb.trajectory.find(TOOL_WRITE_WIKI)
    assert steps, "轨迹中没有 Write_Wiki 步骤"
    return steps[-1].input_summary.get("metadata", {}) or {}


def _extract_read_metadata(sb: HarnessSandbox) -> dict:
    """从轨迹中提取 RetrieverAgent 从 Wiki 读到的 metadata。"""
    steps = sb.trajectory.find(TOOL_READ_WIKI)
    assert steps, "轨迹中没有 Read_Wiki 步骤"
    return steps[-1].output_summary.get("metadata", {}) or {}


def _extract_final_query(sb: HarnessSandbox) -> str:
    """从轨迹中提取 RetrieverAgent 最终发给向量检索的 query。"""
    steps = sb.trajectory.find(TOOL_VECTOR_SEARCH)
    assert steps, "轨迹中没有 vector_Search 步骤"
    return steps[-1].input_summary.get("query", "")


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_wiki_metadata_roundtrip_no_loss(sandbox: HarnessSandbox):
    """断言 IntentAgent 写入 Wiki 的 preferences 与 RetrieverAgent 读到的 metadata 完全一致。

    这是保真度的第一关: 写什么就必须读什么，不能在 Wiki 存取过程中丢字段。
    """
    # 构造一个能同时命中 style / color / material / category 的输入
    sandbox.run_user_turn(
        user_text="我喜欢北欧风蓝色布艺沙发，现代简约，质感很好",
        user_id="u_fidelity_roundtrip",
    )
    written = _extract_written_preferences(sandbox)
    read_back = _extract_read_metadata(sandbox)

    print("写入 Wiki 的 preferences:", written)
    print("从 Wiki 读回的 metadata:", read_back)

    # 关键字段必须一致 (None 也保持 None)
    for key in ("style", "color", "material", "category", "sentiment"):
        assert written.get(key) == read_back.get(key), \
            f"字段 {key} 在 Wiki 往返后不一致: " \
            f"written={written.get(key)} read_back={read_back.get(key)}"


def test_clip_query_contains_all_nonnull_features(sandbox: HarnessSandbox):
    """断言最终 CLIP query 字符串融合了所有非空实体特征。

    RetrieverAgent.build_clip_query 的拼接规则:
        parts = [style, color, material] (过滤空值)
        clip_query = "".join(parts) + " " + category
    因此 style / color / material 三个非空特征必须全部出现在 query 中。
    """
    sandbox.run_user_turn(
        user_text="我喜欢北欧风蓝色布艺沙发，现代简约",
        user_id="u_fidelity_query",
    )
    written = _extract_written_preferences(sandbox)
    final_query = _extract_final_query(sandbox)

    print("preferences:", written)
    print("最终 CLIP query:", repr(final_query))

    # 统计非空特征数
    feature_keys = ("style", "color", "material")
    non_null_features = [written[k] for k in feature_keys if written.get(k)]
    # 至少应该提取出 3 个特征 (北欧/蓝色/布艺)
    assert len(non_null_features) >= 3, \
        f"规则提取未命中足够特征: {written}"

    # 每个非空特征都必须出现在最终 query 中
    missing = []
    for feat in non_null_features:
        if str(feat) not in final_query:
            missing.append(feat)

    loss_rate = len(missing) / len(non_null_features) * 100.0
    print(f"融合特征数: {len(non_null_features)}, 丢失特征: {missing}, "
          f"丢失率: {loss_rate:.2f}%")

    # 工单红线: 信息丢失率必须 = 0%
    assert loss_rate == 0.0, \
        f"信息丢失率 = {loss_rate:.2f}% > 0%! 未融合特征: {missing}"


def test_information_loss_rate_zero_with_rich_input(sandbox: HarnessSandbox):
    """用更丰富的输入再跑一次，确保多种风格/颜色/材质组合下丢失率仍为 0%。"""
    test_cases = [
        "我想要一款工业风黑色金属椅子",
        "复古红色皮革沙发推荐",
        "极简白色塑料收纳盒",
    ]
    total_features = 0
    total_missing = 0
    for i, text in enumerate(test_cases):
        # 每个用例独立 user_id，避免 Wiki 文档互相覆盖
        sandbox.run_user_turn(user_text=text, user_id=f"u_rich_{i}")
        written = _extract_written_preferences(sandbox)
        final_query = _extract_final_query(sandbox)
        feats = [written[k] for k in ("style", "color", "material") if written.get(k)]
        for f in feats:
            total_features += 1
            if str(f) not in final_query:
                total_missing += 1
                print(f"[丢失] text={text} feat={f} query={final_query}")

    loss_rate = (total_missing / total_features * 100.0) if total_features else 0.0
    print(f"总特征数: {total_features}, 丢失: {total_missing}, 丢失率: {loss_rate:.2f}%")
    assert loss_rate == 0.0, f"信息丢失率 {loss_rate:.2f}% > 0%"
