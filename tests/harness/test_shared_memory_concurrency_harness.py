# -*- coding: utf-8 -*-
"""
并发争抢与死锁测试 (Shared Memory Concurrency Harness)
=======================================================

工单要求:
    并发启动 50 组协同 Agent 实例，断言:
        1. 多 Agent 同时读写共享记忆库时不发生死锁或脏读。
        2. 事务冲突率 ≤ 1%。
    使用 concurrent.futures.ThreadPoolExecutor 实现并发。

实现说明:
    - 50 个独立 user_id，每个用户跑一次完整协同 (Intent 写 -> Retriever 读)。
    - 每个 user 独立断言: 我刚写入的 preferences 必须能被我自己读回 (无脏读)。
    - 任何异常 (sqlite3.OperationalError / Timeout / AssertionError) 都计入事务冲突。
    - 为避免 networkx.save() 的 JSON 文件 IO 竞争拖慢测试，统一打桩掉 save()。
"""
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from harness_sandbox import HarnessSandbox  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: 全测试共享一个沙箱 (共享同一个 SQLite / fakeredis / networkx 实例)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def shared_sandbox():
    sb = HarnessSandbox()
    sb.bootstrap()

    # 打桩掉 graph.save() —— 压测关注内存层并发，不关注 JSON 持久化 IO
    orig_save = sb.store.graph.save
    sb.store.graph.save = lambda: None  # type: ignore

    yield sb

    sb.store.graph.save = orig_save  # type: ignore
    sb.teardown()


# ---------------------------------------------------------------------------
# 单个用户的协同任务
# ---------------------------------------------------------------------------
def _single_user_turn(sb: HarnessSandbox, user_idx: int, results: list,
                       lock: threading.Lock) -> dict:
    """模拟单个用户: IntentAgent 写偏好 -> RetrieverAgent 读回并校验。

    返回:
        {"user_id": ..., "ok": bool, "error": str|None,
         "write_latency_ms": float, "read_latency_ms": float}
    """
    user_id = f"u_concurrent_{user_idx:03d}"
    # 每个用户用不同的偏好特征，便于校验无脏读
    color_pool = ["蓝色", "白色", "黑色", "灰色", "棕色"]
    material_pool = ["布艺", "实木", "金属", "皮革", "塑料"]
    style_pool = ["北欧", "现代", "古典", "简约", "复古"]
    color = color_pool[user_idx % len(color_pool)]
    material = material_pool[user_idx % len(material_pool)]
    style = style_pool[user_idx % len(style_pool)]
    text = f"我喜欢{style}风{color}{material}家具"

    record = {"user_id": user_id, "ok": False, "error": None,
              "write_latency_ms": 0.0, "read_latency_ms": 0.0}
    try:
        # ---- 写阶段: IntentAgent.analyze (内部 Extract + Write_Wiki + Publish) ----
        t0 = time.perf_counter()
        intent_out = sb.intent_agent.analyze(user_id=user_id, text=text)
        record["write_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        written_prefs = intent_out["preferences"]

        # ---- 读阶段: RetrieverAgent 读自己的 Wiki (并发场景下直接读库) ----
        t1 = time.perf_counter()
        # 直接调用 build_clip_query 等价于 RetrieverAgent.Read_Wiki + vector_Search 中的读库动作
        # (stream 信号在多 worker 共享 consumer group 下会被随机抢走，这里聚焦 Wiki 读写一致性)
        plan = sb.retriever_agent.build_clip_query(user_id=user_id)
        record["read_latency_ms"] = round((time.perf_counter() - t1) * 1000, 2)

        # ---- 脏读校验: 读回的 metadata 必须与写入的 preferences 完全一致 ----
        read_meta = plan["preferences"]
        for key in ("style", "color", "material"):
            wv = written_prefs.get(key)
            rv = read_meta.get(key)
            # None 也要相等
            if wv != rv:
                raise AssertionError(
                    f"脏读! user={user_id} key={key} "
                    f"written={wv} read={rv}"
                )
        record["ok"] = True
    except Exception as e:  # 捕获所有异常作为事务冲突
        record["error"] = f"{type(e).__name__}: {e}"

    with lock:
        results.append(record)
    return record


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_50_agents_no_deadlock_no_dirty_read(shared_sandbox: HarnessSandbox):
    """50 组协同 Agent 并发，断言无死锁、无脏读、事务冲突率 ≤ 1%。"""
    N = 50
    results: list = []
    lock = threading.Lock()

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16, thread_name_prefix="agent") as pool:
        futures = [pool.submit(_single_user_turn, shared_sandbox, i, results, lock)
                   for i in range(N)]
        # 给一个上限超时 (30 秒)，防止死锁永久阻塞
        for fut in as_completed(futures, timeout=30):
            fut.result()
    wall_time = time.perf_counter() - t_start

    # 统计
    ok_cnt = sum(1 for r in results if r["ok"])
    fail_cnt = N - ok_cnt
    conflict_rate = fail_cnt / N * 100.0
    avg_write = sum(r["write_latency_ms"] for r in results) / N
    avg_read = sum(r["read_latency_ms"] for r in results) / N

    print(f"\n========== 并发 {N} Agent 测试结果 ==========")
    print(f"总耗时: {wall_time:.2f}s")
    print(f"成功: {ok_cnt}/{N}, 失败: {fail_cnt}")
    print(f"事务冲突率: {conflict_rate:.2f}%")
    print(f"平均写延迟: {avg_write:.2f}ms, 平均读延迟: {avg_read:.2f}ms")
    if fail_cnt:
        print("失败详情:")
        for r in results:
            if not r["ok"]:
                print(f"  - {r['user_id']}: {r['error']}")

    # 工单红线: 事务冲突率 ≤ 1%
    assert conflict_rate <= 1.0, \
        f"事务冲突率 {conflict_rate:.2f}% > 1% 红线! 失败数={fail_cnt}"
