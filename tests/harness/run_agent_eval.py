# -*- coding: utf-8 -*-
"""
Agent Harness 测试运行入口
===========================

职责:
    1. 调用 pytest 运行 tests/harness/ 下全部测试用例。
    2. 额外跑 N 组完整双 Agent 协同样本，导出轨迹到 trajectory_trace.json。
    3. 计算并打印核心指标:
        - Tool Call 准确率   (轨迹是否严格符合工单约定序列)
        - 任务完成率         (每个 run 是否成功走完 Extract->Write->Subscribe->Read->Search)
        - 指代消解 Recall    (含指代表述的输入是否正确融合偏好特征到最终 query)
    4. 输出测试通过率。

用法:
    python tests/harness/run_agent_eval.py
"""
from __future__ import annotations

import os
import sys
import json
import time
import subprocess
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# 路径初始化
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import config  # noqa: E402
from harness_sandbox import (  # noqa: E402
    HarnessSandbox,
    TrajectoryValidator,
    EXPECTED_TOOL_SEQUENCE,
    TOOL_VECTOR_SEARCH,
)


# ---------------------------------------------------------------------------
# 评测样本: 含指代表述的用户输入 (工单要求 "搭配我周一上传的那款蓝色沙发")
# ---------------------------------------------------------------------------
EVAL_SAMPLES: List[Dict[str, Any]] = [
    {"text": "搭配我周一上传的那款蓝色沙发", "user_id": "u_eval_001",
     "expected_features": ["蓝色"]},
    {"text": "我喜欢北欧风蓝色布艺沙发", "user_id": "u_eval_002",
     "expected_features": ["Nordic", "蓝色", "布艺"]},
    {"text": "再来一款复古红色皮革椅子", "user_id": "u_eval_003",
     "expected_features": ["复古", "红色", "皮革"]},
    {"text": "工业风黑色金属书架推荐", "user_id": "u_eval_004",
     "expected_features": ["工业", "黑色", "金属"]},
    {"text": "搭配我上次看的那款白色塑料收纳盒", "user_id": "u_eval_005",
     "expected_features": ["白色", "塑料"]},
]


def run_pytest() -> Dict[str, Any]:
    """调用 pytest 跑全部 harness 测试，返回结果摘要。"""
    print("=" * 70)
    print("[1/3] 运行 pytest 测试套件 ...")
    print("=" * 70)
    pytest_args = [
        sys.executable, "-m", "pytest",
        os.path.join(_HERE, ""),
        "-v", "--tb=short",
    ]
    proc = subprocess.run(
        pytest_args,
        cwd=_PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": _PROJECT_ROOT,
             "HF_HUB_OFFLINE": "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(proc.stdout[-3000:])
    if proc.stderr:
        print("[stderr]", proc.stderr[-1000:])
    passed = proc.returncode == 0
    return {
        "pytest_exit_code": proc.returncode,
        "pytest_passed": passed,
    }


def collect_traces_and_metrics() -> Dict[str, Any]:
    """跑 N 组协同样本，收集轨迹并计算指标。"""
    print("\n" + "=" * 70)
    print("[2/3] 采集双 Agent 协同轨迹样本 ...")
    print("=" * 70)

    # 共享一个 sandbox (一次 bootstrap，跑多 user_id)
    sb = HarnessSandbox()
    sb.bootstrap()
    # 压测中 graph.save 的 JSON IO 不是关注点
    sb.store.graph.save = lambda: None  # type: ignore

    traces: List[Dict[str, Any]] = []
    tool_call_correct = 0
    task_completed = 0
    anaphora_total = 0
    anaphora_recalled = 0

    for i, sample in enumerate(EVAL_SAMPLES):
        # 每个样本独立子轨迹 (清空之前的 steps)
        sb.trajectory.steps.clear()
        sb.trajectory.run_id = f"eval_run_{i+1:03d}"
        t0 = time.perf_counter()
        try:
            out = sb.run_user_turn(
                user_text=sample["text"],
                user_id=sample["user_id"],
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            # ---- Tool Call 准确率 ----
            try:
                TrajectoryValidator.assert_strict_sequence(sb.trajectory)
                tool_call_correct += 1
                seq_ok = True
            except AssertionError:
                seq_ok = False
            # ---- 任务完成率: 最终拿到非空检索结果 ----
            results = (out.get("retriever_output") or {}).get("results", {}).get("results", [])
            task_ok = seq_ok and len(results) > 0
            if task_ok:
                task_completed += 1
            # ---- 指代消解 Recall ----
            is_anaphora = any(w in sample["text"] for w in
                              ["那款", "上次", "周一", "之前"])
            if is_anaphora:
                anaphora_total += 1
                # 检查最终 query 是否融合了 expected_features
                search_steps = sb.trajectory.find(TOOL_VECTOR_SEARCH)
                final_query = (search_steps[-1].input_summary.get("query", "")
                               if search_steps else "")
                hit = all(f in final_query for f in sample["expected_features"])
                if hit:
                    anaphora_recalled += 1
        except Exception as e:
            wall_ms = (time.perf_counter() - t0) * 1000
            out = {"error": str(e)}
            seq_ok = False
        # 记录轨迹
        trace_dict = sb.trajectory.to_dict()
        trace_dict["sample"] = sample
        trace_dict["wall_ms"] = round(wall_ms, 2)
        traces.append(trace_dict)
        print(f"  [{i+1}/{len(EVAL_SAMPLES)}] {sample['text']} "
              f"-> seq_ok={seq_ok} wall={wall_ms:.0f}ms")

    sb.teardown()

    n = len(EVAL_SAMPLES)
    metrics = {
        "total_runs": n,
        "tool_call_accuracy": round(tool_call_correct / n, 4),
        "task_completion_rate": round(task_completed / n, 4),
        "anaphora_recall": round(anaphora_recalled / anaphora_total, 4) if anaphora_total else 0.0,
        "anaphora_total": anaphora_total,
        "anaphora_recalled": anaphora_recalled,
    }
    return {"traces": traces, "metrics": metrics}


def export_trace_json(payload: Dict[str, Any]) -> str:
    """导出轨迹追踪日志到 tests/harness/trajectory_trace.json。"""
    out_path = os.path.join(_HERE, "trajectory_trace.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[3/3] 轨迹日志已导出: {out_path}")
    return out_path


def main() -> int:
    # 1) pytest
    pytest_result = run_pytest()
    # 2) 轨迹 + 指标
    trace_result = collect_traces_and_metrics()
    # 3) 导出
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pytest": pytest_result,
        "metrics": trace_result["metrics"],
        "expected_tool_sequence": EXPECTED_TOOL_SEQUENCE,
        "traces": trace_result["traces"],
    }
    out_path = export_trace_json(payload)

    # 汇总打印
    m = trace_result["metrics"]
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    print(f"  pytest 通过率        : {'PASS' if pytest_result['pytest_passed'] else 'FAIL'} "
          f"(exit={pytest_result['pytest_exit_code']})")
    print(f"  Tool Call 准确率     : {m['tool_call_accuracy']*100:.1f}% "
          f"({int(m['tool_call_accuracy']*m['total_runs'])}/{m['total_runs']})")
    print(f"  任务完成率           : {m['task_completion_rate']*100:.1f}% "
          f"({int(m['task_completion_rate']*m['total_runs'])}/{m['total_runs']})")
    print(f"  指代消解 Recall      : {m['anaphora_recall']*100:.1f}% "
          f"({m['anaphora_recalled']}/{m['anaphora_total']})")
    print(f"  轨迹日志文件         : {out_path}")
    return 0 if pytest_result["pytest_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
