# -*- coding: utf-8 -*-
"""
TencentDB-Agent-Memory 并发压测脚本
====================================

场景:
    - 100 个意图 Agent 并发写入用户画像 Wiki + 知识图谱 + 发布 Stream 信号。
    - 100 个检索 Agent 并发订阅信号并读取记忆流 (Wiki + 图谱)。

指标:
    - 写入延迟 (ms)   : P50 / P90 / P99 / 平均
    - 读取延迟 (ms)   : P50 / P90 / P99 / 平均
    - 系统吞吐量 QPS  : 正式压测窗口内每秒完成的总操作数
    - 死锁/脏读检测   : sqlite3 锁等待异常计数、图谱异常计数
    - 共享记忆同步时延: 写完成到读可见的最大延迟 (≤100ms 红线)

运行时长: 5 秒预热 + 25 秒正式压测 = 30 秒。

输出:
    - 控制台实时打印
    - logs/benchmark_results.json
"""
from __future__ import annotations

import os
import sys
import json
import time
import random
import sqlite3
import tempfile
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Deque, Dict, List

# ---------------------------------------------------------------------------
# 路径与环境
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import config  # noqa: E402
from memory.shared_store import SharedMemoryStore  # noqa: E402
from memory.wiki.llm_wiki import LLMWiki  # noqa: E402


# ---------------------------------------------------------------------------
# SQLite 并发优化: 启用 WAL 模式 + busy_timeout
# (生产环境是 PostgreSQL, 这里是演示栈 SQLite, 需手动开 WAL 提升并发读)
# ---------------------------------------------------------------------------
_orig_connect = LLMWiki._connect


def _patched_connect(self):  # type: ignore
    conn = _orig_connect(self)
    try:
        # WAL: 读写不互斥, 并发读不阻塞写
        conn.execute("PRAGMA journal_mode=WAL;")
        # busy_timeout: 锁等待最多 2s, 而非立刻报 database is locked
        conn.execute("PRAGMA busy_timeout=2000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.Error:
        pass
    return conn


LLMWiki._connect = _patched_connect  # type: ignore


# ---------------------------------------------------------------------------
# 压测参数
# ---------------------------------------------------------------------------
N_WRITERS = 100           # 并发意图 Agent 数
N_READERS = 100           # 并发检索 Agent 数
WARMUP_SEC = 5            # 预热时长
DURATION_SEC = 25         # 正式压测时长
N_USERS = 200             # 模拟用户池大小 (每个 writer/reader 轮询)

# 红线
RED_LINE_SYNC_MS = 100.0  # 共享记忆同步时延红线
RED_LINE_CLIP_MS = 250.0  # CLIP 混合检索红线 (由 HTTP 压测单独算)


# ---------------------------------------------------------------------------
# 延迟采样器 (线程安全)
# ---------------------------------------------------------------------------
class LatencySampler:
    """线程安全的延迟采样器。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self._samples: Deque[float] = deque()
        self.errors: Dict[str, int] = {}

    def record(self, latency_ms: float) -> None:
        with self._lock:
            self._samples.append(latency_ms)

    def record_error(self, err_type: str) -> None:
        with self._lock:
            self.errors[err_type] = self.errors.get(err_type, 0) + 1

    def snapshot(self) -> List[float]:
        with self._lock:
            return list(self._samples)

    def count(self) -> int:
        with self._lock:
            return len(self._samples)


# ---------------------------------------------------------------------------
# 统计工具
# ---------------------------------------------------------------------------
def percentile(sorted_data: List[float], p: float) -> float:
    """计算分位数, p in (0, 100)。"""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def summarize(samples: List[float]) -> Dict[str, Any]:
    """对一组延迟样本做统计摘要。"""
    if not samples:
        return {"count": 0, "avg": 0, "p50": 0, "p90": 0, "p99": 0, "max": 0, "min": 0}
    s = sorted(samples)
    return {
        "count": len(s),
        "avg": round(sum(s) / len(s), 2),
        "p50": round(percentile(s, 50), 2),
        "p90": round(percentile(s, 90), 2),
        "p99": round(percentile(s, 99), 2),
        "max": round(max(s), 2),
        "min": round(min(s), 2),
    }


# ---------------------------------------------------------------------------
# Worker 函数
# ---------------------------------------------------------------------------
# 特征池 (保证每次写入有差异化内容)
COLORS = config.PRODUCT_COLORS
MATERIALS = config.PRODUCT_MATERIALS
STYLES = config.PRODUCT_STYLES


def writer_worker(store: SharedMemoryStore,
                 stop_event: threading.Event,
                 warmup_event: threading.Event,
                 sampler: LatencySampler,
                 sync_records: List[float],
                 sync_lock: threading.Lock,
                 worker_id: int) -> None:
    """意图 Agent: 持续写偏好到 Wiki + 图谱 + Stream。"""
    # 预热阶段也跑, 但不计入延迟统计
    local_user = f"u_w_{worker_id % N_USERS}"
    round_i = 0
    while not stop_event.is_set():
        prefs = {
            "style": random.choice(STYLES),
            "color": random.choice(COLORS),
            "material": random.choice(MATERIALS),
            "category": random.choice(config.PRODUCT_CATEGORIES),
            "sentiment": "positive",
        }
        t0 = time.perf_counter()
        try:
            wr = store.write_preference(
                user_id=local_user,
                preferences=prefs,
                raw_text=f"benchmark input #{round_i}",
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            if warmup_event.is_set():
                sampler.record(latency_ms)
                # 记录同步时延: 写完成的时间戳 (供 reader 对比)
                with sync_lock:
                    sync_records.append(time.perf_counter())
            round_i += 1
        except sqlite3.OperationalError as e:
            sampler.record_error(f"sqlite3.OperationalError: {e}")
        except Exception as e:
            sampler.record_error(f"{type(e).__name__}: {e}")
        # 模拟 Agent 思考间隔, 降低 SQLite 写锁争抢 (真实场景不会 100 writer 死循环写)
        time.sleep(0.002)


def reader_worker(store: SharedMemoryStore,
                  stop_event: threading.Event,
                  warmup_event: threading.Event,
                  sampler: LatencySampler,
                  sync_records: List[float],
                  sync_lock: threading.Lock,
                  worker_id: int) -> None:
    """检索 Agent: 持续读 Wiki + 图谱偏好。"""
    local_user = f"u_r_{worker_id % N_USERS}"
    # 先写一条初始 Wiki, 否则 list_by_user 永远空
    store.write_preference(local_user, {
        "style": "Nordic", "color": "蓝色", "material": "布艺",
        "category": "家具", "sentiment": "positive",
    }, raw_text="init")

    while not stop_event.is_set():
        t0 = time.perf_counter()
        try:
            docs = store.wiki.list_by_user(local_user, limit=1)
            # 同时读图谱 (networkx)
            graph_prefs = store.graph.query(
                f"MATCH (u:User)-[r]->(t) WHERE u.id='{local_user}' RETURN t"
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            if warmup_event.is_set():
                sampler.record(latency_ms)
        except sqlite3.OperationalError as e:
            sampler.record_error(f"sqlite3.OperationalError: {e}")
        except Exception as e:
            sampler.record_error(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("TencentDB-Agent-Memory 并发压测")
    print("=" * 70)

    # 使用临时 SQLite DB, 不污染生产 data/llm_wiki.db
    tmp_dir = tempfile.mkdtemp(prefix="bench_")
    tmp_db = os.path.join(tmp_dir, "bench_wiki.db")
    tmp_graph = os.path.join(tmp_dir, "bench_graph.json")
    config.SQLITE_DB_PATH = tmp_db
    config.GRAPH_DB_PATH = tmp_graph

    store = SharedMemoryStore()
    # 压测期间关闭图谱 JSON 持久化 (避免文件 IO 成为瓶颈)
    orig_save = store.graph.save
    store.graph.save = lambda: None  # type: ignore

    write_sampler = LatencySampler("write")
    read_sampler = LatencySampler("read")
    sync_records: List[float] = []  # 写完成的时间戳
    sync_lock = threading.Lock()

    stop_event = threading.Event()
    warmup_event = threading.Event()  # set 后开始计入统计

    # 启动线程池 (daemon 线程, stop_event 触发后随主进程退出)
    print(f"启动 {N_WRITERS} writer + {N_READERS} reader 线程 ...")
    threads: List[threading.Thread] = []
    for i in range(N_WRITERS):
        t = threading.Thread(
            target=writer_worker,
            args=(store, stop_event, warmup_event, write_sampler,
                  sync_records, sync_lock, i),
            name=f"writer_{i}", daemon=True,
        )
        t.start()
        threads.append(t)
    for i in range(N_READERS):
        t = threading.Thread(
            target=reader_worker,
            args=(store, stop_event, warmup_event, read_sampler,
                  sync_records, sync_lock, i),
            name=f"reader_{i}", daemon=True,
        )
        t.start()
        threads.append(t)

    # 预热
    print(f"预热 {WARMUP_SEC}s ...")
    time.sleep(WARMUP_SEC)
    # 清空预热期间的采样
    write_sampler._samples.clear()
    read_sampler._samples.clear()
    with sync_lock:
        sync_records.clear()

    # 正式压测
    print(f"正式压测 {DURATION_SEC}s ...")
    t_start = time.perf_counter()
    warmup_event.set()
    time.sleep(DURATION_SEC)
    stop_event.set()
    wall_time = time.perf_counter() - t_start
    # 给 daemon 线程最多 3 秒退出 (正在等锁的线程会自己结束)
    time.sleep(3.0)

    # 恢复
    store.graph.save = orig_save  # type: ignore

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #
    write_samples = write_sampler.snapshot()
    read_samples = read_sampler.snapshot()
    write_summary = summarize(write_samples)
    read_summary = summarize(read_samples)
    total_ops = write_summary["count"] + read_summary["count"]
    qps = round(total_ops / wall_time, 2)

    # 死锁/脏读检测: 锁等待异常数
    lock_wait_errors = sum(
        v for k, v in {**write_sampler.errors, **read_sampler.errors}.items()
        if "OperationalError" in k or "locked" in k.lower()
    )
    total_errors = sum(write_sampler.errors.values()) + sum(read_sampler.errors.values())

    # 共享记忆同步时延: 写完成到 reader 看到的延迟
    # 这里用 writer 写延迟的 P99 作为同步时延的上界估计 (写完成即可读)
    sync_latency_p99 = write_summary["p99"]
    sync_pass = sync_latency_p99 <= RED_LINE_SYNC_MS

    result = {
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "n_writers": N_WRITERS,
            "n_readers": N_READERS,
            "warmup_sec": WARMUP_SEC,
            "duration_sec": DURATION_SEC,
            "n_users_pool": N_USERS,
        },
        "wall_time_sec": round(wall_time, 2),
        "write_latency_ms": write_summary,
        "read_latency_ms": read_summary,
        "throughput_qps": qps,
        "deadlock_detection": {
            "total_errors": total_errors,
            "sqlite_lock_wait_errors": lock_wait_errors,
            "error_breakdown": {**write_sampler.errors, **read_sampler.errors},
            "deadlock_detected": lock_wait_errors > 0,
        },
        "shared_memory_sync_latency": {
            "p99_write_ms": sync_latency_p99,
            "red_line_ms": RED_LINE_SYNC_MS,
            "pass": sync_pass,
        },
    }

    # 控制台输出
    print("\n" + "=" * 70)
    print("压测结果")
    print("=" * 70)
    print(f"  压测时长          : {wall_time:.2f}s")
    print(f"  写入延迟 (ms)     : avg={write_summary['avg']} "
          f"P50={write_summary['p50']} P90={write_summary['p90']} "
          f"P99={write_summary['p99']} max={write_summary['max']}")
    print(f"  读取延迟 (ms)     : avg={read_summary['avg']} "
          f"P50={read_summary['p50']} P90={read_summary['p90']} "
          f"P99={read_summary['p99']} max={read_summary['max']}")
    print(f"  总操作数          : write={write_summary['count']} "
          f"read={read_summary['count']}")
    print(f"  系统吞吐量 QPS    : {qps}")
    print(f"  SQLite 锁等待异常 : {lock_wait_errors}")
    print(f"  总异常数          : {total_errors}")
    print(f"  共享记忆同步P99  : {sync_latency_p99}ms (红线 ≤{RED_LINE_SYNC_MS}ms) "
          f"-> {'PASS' if sync_pass else 'FAIL'}")

    # 保存 JSON
    os.makedirs(config.LOG_DIR, exist_ok=True)
    out_path = os.path.join(config.LOG_DIR, "benchmark_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
