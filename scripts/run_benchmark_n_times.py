"""Chạy benchmark checklist N lần liên tiếp trên CÙNG 1 cấu hình, lấy accuracy/recall/precision
trung bình + độ lệch (min-max) - dùng làm baseline đáng tin cậy trước khi so sánh bất kỳ thay đổi
nào, vì pipeline có nhiễu non-determinism (đã xác nhận: cùng input, cùng temperature=0 vẫn ra kết
quả hơi khác nhau giữa các lần chạy).

Tái dùng process_one_item() từ scripts/evaluate_checklist.py và evaluate() từ evaluation/evaluate.py -
không viết lại logic chấm điểm/tính metric.

Usage: python scripts/run_benchmark_n_times.py [--n 3] [--checklist path.json] [--contract-id 1]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from evaluate_checklist import _DEFAULT_CHECKLIST, process_one_item  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evaluation.evaluate import _DEFAULT_GROUND_TRUTH, _load_ground_truth, evaluate  # noqa: E402

logger = logging.getLogger(__name__)


def _run_once(contract_id: int, items: list[dict], max_workers: int, requirements_map: dict | None) -> dict[str, dict]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_one_item, contract_id, item, i, len(items), requirements_map)
            for i, item in enumerate(items, start=1)
        ]
        results = [f.result() for f in futures]
    return {r["item_id"]: r for r in results}


def _summarize(values: list[float]) -> str:
    if not values:
        return "n/a"
    mean = statistics.mean(values)
    return f"mean={mean:.3f}  min={min(values):.3f}  max={max(values):.3f}  (các lần: {[round(v, 3) for v in values]})"


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=3, help="Số lần chạy lặp lại (mặc định 3)")
    parser.add_argument("--checklist", default=str(_DEFAULT_CHECKLIST))
    parser.add_argument("--ground-truth", default=str(_DEFAULT_GROUND_TRUTH))
    parser.add_argument("--contract-id", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument(
        "--requirements", default=None,
        help="File JSON đã phân rã sẵn (từ scripts/dump_requirements.py) - nếu truyền, BỎ QUA bước "
        "phân rã LLM ở mỗi lần chạy, dùng thẳng requirements đã lưu (tiện benchmark lặp N lần khi "
        "chỉ đang thử retrieval/evaluate, không tốn gọi lại phân rã mỗi lần).",
    )
    args = parser.parse_args()

    checklist = json.loads(Path(args.checklist).read_text(encoding="utf-8"))
    items = checklist["items"]
    ground_truth = _load_ground_truth(Path(args.ground_truth))
    requirements_map = json.loads(Path(args.requirements).read_text(encoding="utf-8")) if args.requirements else None

    accuracies, recalls, precisions = [], [], []
    for run_idx in range(1, args.n + 1):
        logger.info("===== Lần chạy %d/%d =====", run_idx, args.n)
        system_output = _run_once(args.contract_id, items, args.max_workers, requirements_map)
        report = evaluate(ground_truth, system_output)
        summary = report["summary"]
        logger.info(
            "Lần %d: accuracy=%s recall=%s precision=%s",
            run_idx, summary["status_accuracy"], summary["mean_retrieval_recall"], summary["mean_retrieval_precision"],
        )
        if summary["status_accuracy"] is not None:
            accuracies.append(summary["status_accuracy"])
        if summary["mean_retrieval_recall"] is not None:
            recalls.append(summary["mean_retrieval_recall"])
        if summary["mean_retrieval_precision"] is not None:
            precisions.append(summary["mean_retrieval_precision"])

    logger.info("===== Tổng kết %d lần chạy =====", args.n)
    logger.info("Accuracy:  %s", _summarize(accuracies))
    logger.info("Recall:    %s", _summarize(recalls))
    logger.info("Precision: %s", _summarize(precisions))


if __name__ == "__main__":
    main()
