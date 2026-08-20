"""So sánh output hệ thống chấm checklist với ground truth, tính metric retrieval + evaluation.

Cách dùng:
    python evaluation/evaluate.py --system-output path/to/system_output.json [--ground-truth path] [--report-out path]

Input mong đợi:
- ground truth: data/benchmark/bm01_checklist_ground_truth.json (định dạng do agent tạo, xem field "items").
- system output: kết quả trả về từ services.checklist_service.evaluate_checklist_batch(), tức 1 trong 2 dạng:
    - list[dict] với các key: item_id, status, cited_clauses (list các Điều đã gộp, mỗi Điều có
      article_number/article_title/score/clauses - xem rag.builder.group_by_article), ...
    - {"evaluations": [...]} (định dạng response của POST /api/checklist)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from config.logging_config import setup_logging  # noqa: E402
from evaluation.checklist import evaluate  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_GROUND_TRUTH = Path(__file__).parent.parent / "data" / "benchmark" / "bm01_checklist_ground_truth.json"
_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "output"


def _latest_system_output() -> Path | None:
    """File 'contract*_system_output.json' mới nhất trong data/output/ (theo mtime) - dùng làm mặc
    định cho --system-output khi không truyền. Mỗi hợp đồng chỉ giữ ĐÚNG 1 file (scripts/
    evaluate_checklist.py ghi đè mỗi lần chạy, không tích luỹ theo ngày-giờ) - lấy mtime mới nhất
    để biết hợp đồng nào vừa chấm gần đây nhất trong số các file hiện có."""
    candidates = sorted(_OUTPUT_DIR.glob("*_system_output.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_ground_truth(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in data["items"]}


def _load_system_output(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    evaluations = data["evaluations"] if isinstance(data, dict) and "evaluations" in data else data
    return {e["item_id"]: e for e in evaluations}


def _log_report(report: dict) -> None:
    summary = report["summary"]
    logger.info("=== Tổng quan ===")
    logger.info("Tổng số mục checklist: %s", summary["total_items"])
    logger.info("Số mục có kết luận rõ ràng (pass/fail) dùng để tính accuracy: %s", summary["conclusive_items_evaluated"])
    logger.info("Độ chính xác kết luận (status accuracy): %s", summary["status_accuracy"])
    logger.info("Recall@k trung bình (retrieval): %s", summary["mean_retrieval_recall"])
    logger.info("Precision@k trung bình (retrieval): %s", summary["mean_retrieval_precision"])
    if summary["missing_in_system_output"]:
        logger.warning("Mục thiếu trong output hệ thống: %s", summary["missing_in_system_output"])

    logger.info("=== Chi tiết theo mục ===")
    header = f"{'ID':6} {'GT':12} {'Hệ thống':12} {'Khớp':6} {'Recall':7} {'Precision':9}"
    logger.info(header)
    logger.info("-" * len(header))
    for row in report["items"]:
        retrieval = row["retrieval"] or {}
        match = "-" if row["status_match"] is None else ("✓" if row["status_match"] else "✗")
        logger.info(
            "%-6s %-12s %-12s %-6s %-7s %-9s",
            row["item_id"],
            row["ground_truth_status"],
            str(row["system_status"]),
            match,
            str(retrieval.get("recall")),
            str(retrieval.get("precision")),
        )


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--system-output", type=Path, default=None,
        help="File JSON output của hệ thống cần đánh giá - mặc định tự lấy file mới nhất trong data/output/",
    )
    parser.add_argument("--ground-truth", type=Path, default=_DEFAULT_GROUND_TRUTH, help="File JSON ground truth")
    parser.add_argument(
        "--report-out", type=Path, default=None,
        help="Đường dẫn ghi report chi tiết - mặc định data/output/eval_report_{system_output_stem}.json, "
        "GHI ĐÈ lần chạy trước (chỉ giữ 1 bản mới nhất).",
    )
    parser.add_argument("--no-report-out", action="store_true", help="Không ghi file report, chỉ in ra log")
    args = parser.parse_args()

    system_output_path = args.system_output or _latest_system_output()
    if system_output_path is None:
        parser.error(f"Không tìm thấy file *_system_output_*.json nào trong {_OUTPUT_DIR} - chạy scripts/evaluate_checklist.py trước, hoặc truyền --system-output.")
    logger.info("Dùng system output: %s", system_output_path)

    ground_truth = _load_ground_truth(args.ground_truth)
    system_output = _load_system_output(system_output_path)

    report = evaluate(ground_truth, system_output)
    _log_report(report)

    if not args.no_report_out:
        if args.report_out:
            out_path = args.report_out
        else:
            label = system_output_path.stem.removesuffix("_system_output")
            out_path = Path(__file__).resolve().parent.parent / "data" / "output" / f"eval_report_{label}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Đã ghi report chi tiết vào %s", out_path)


if __name__ == "__main__":
    main()
