"""So sánh output hệ thống chấm checklist với ground truth, tính metric retrieval + evaluation.

Cách dùng:
    python eval/evaluate.py --system-output path/to/system_output.json [--ground-truth path] [--report-out path]

Input mong đợi:
- ground truth: data/benchmark/bm01_checklist_ground_truth.json (định dạng do agent tạo, xem field "items").
- system output: kết quả trả về từ services.checklist_service.evaluate_checklist_batch(), tức 1 trong 2 dạng:
    - list[dict] với các key: item_id, status, cited_clauses (list các Điều đã gộp, mỗi Điều có
      article_number/article_title/score/clauses - xem retrieval.vector_retriever._group_by_article), ...
    - {"evaluations": [...]} (định dạng response của POST /api/checklist)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_GROUND_TRUTH = Path(__file__).parent.parent / "data" / "benchmark" / "bm01_checklist_ground_truth.json"
_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "output"


def _latest_system_output() -> Path | None:
    """File 'contract*_system_output_*.json' mới nhất trong data/output/ (theo mtime) - dùng làm
    mặc định cho --system-output khi không truyền, vì tên file giờ luôn có hậu tố ngày-giờ (xem
    scripts/evaluate_checklist.py) nên không còn 1 đường dẫn cố định để trỏ mặc định tới."""
    candidates = sorted(_OUTPUT_DIR.glob("*_system_output_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None

# Trạng thái coi là "có kết luận rõ ràng" để tính accuracy pass/fail; các mục ground truth
# no_info/not_applicable không có cách nào hệ thống "đoán đúng" nên loại khỏi accuracy,
# nhưng vẫn được liệt kê riêng để biết hệ thống có tự nhận ra thiếu thông tin không.
_CONCLUSIVE_STATUSES = {"pass", "fail"}


def _load_ground_truth(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in data["items"]}


def _load_system_output(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    evaluations = data["evaluations"] if isinstance(data, dict) and "evaluations" in data else data
    return {e["item_id"]: e for e in evaluations}


def _extract_clause_number(text: str) -> str | None:
    """Rút số Điều đầu tiên từ chuỗi kiểu 'Điều 15.1' hay '15' -> '15'."""
    match = re.search(r"(\d+)", text)
    return match.group(1) if match else None


def _normalize_clause_set(clauses: list[str]) -> set[str]:
    numbers = {_extract_clause_number(c) for c in clauses}
    return {n for n in numbers if n is not None}


def _retrieval_metrics(predicted_clauses: list[dict], relevant_clauses: list[str]) -> dict:
    relevant_set = _normalize_clause_set(relevant_clauses)
    predicted_set = _normalize_clause_set([str(c.get("number", "")) for c in predicted_clauses])

    if not relevant_set:
        return {"recall": None, "precision": None, "hit": None}

    hit = relevant_set & predicted_set
    recall = len(hit) / len(relevant_set)
    precision = len(hit) / len(predicted_set) if predicted_set else 0.0
    return {"recall": round(recall, 3), "precision": round(precision, 3), "hit": sorted(hit)}


def _normalize_status(status: str) -> str:
    return status.strip().lower()


def evaluate(ground_truth: dict[str, dict], system_output: dict[str, dict]) -> dict:
    per_item = []
    for item_id, gt_item in ground_truth.items():
        gt = gt_item["ground_truth"]
        gt_status = _normalize_status(gt["status"])
        sys_item = system_output.get(item_id)

        row = {
            "item_id": item_id,
            "category": gt_item["category"],
            "ground_truth_status": gt_status,
            "system_status": None,
            "status_match": None,
            "retrieval": None,
            "missing_in_system_output": sys_item is None,
        }

        if sys_item is not None:
            sys_status = _normalize_status(sys_item.get("status", ""))
            row["system_status"] = sys_status
            if gt_status in _CONCLUSIVE_STATUSES:
                row["status_match"] = sys_status == gt_status
            # cited_clauses giờ là danh sách Điều đã gộp (không phải Khoản phẳng) - ground truth
            # cũng chỉ liệt kê ở cấp Điều nên so khớp theo article_number là đủ và đúng.
            predicted_articles = [{"number": g.get("article_number", "")} for g in sys_item.get("cited_clauses", [])]
            row["retrieval"] = _retrieval_metrics(predicted_articles, gt.get("relevant_clauses", []))

        per_item.append(row)

    conclusive = [r for r in per_item if r["ground_truth_status"] in _CONCLUSIVE_STATUSES and not r["missing_in_system_output"]]
    accuracy = sum(1 for r in conclusive if r["status_match"]) / len(conclusive) if conclusive else None

    retrieval_rows = [r["retrieval"] for r in per_item if r["retrieval"] and r["retrieval"]["recall"] is not None]
    mean_recall = sum(r["recall"] for r in retrieval_rows) / len(retrieval_rows) if retrieval_rows else None
    mean_precision = sum(r["precision"] for r in retrieval_rows) / len(retrieval_rows) if retrieval_rows else None

    missing = [r["item_id"] for r in per_item if r["missing_in_system_output"]]

    return {
        "summary": {
            "total_items": len(per_item),
            "conclusive_items_evaluated": len(conclusive),
            "status_accuracy": round(accuracy, 3) if accuracy is not None else None,
            "mean_retrieval_recall": round(mean_recall, 3) if mean_recall is not None else None,
            "mean_retrieval_precision": round(mean_precision, 3) if mean_precision is not None else None,
            "missing_in_system_output": missing,
        },
        "items": per_item,
    }


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
        help="Đường dẫn ghi report chi tiết - mặc định tự đặt tên có hậu tố ngày-giờ trong data/output/. "
        "Nếu truyền đường dẫn cụ thể, hậu tố ngày-giờ vẫn được chèn trước phần đuôi file, tránh ghi đè lần trước.",
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.report_out:
            out_path = args.report_out.with_stem(f"{args.report_out.stem}_{timestamp}")
        else:
            out_path = Path(__file__).resolve().parent.parent / "data" / "output" / f"eval_report_{timestamp}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Đã ghi report chi tiết vào %s", out_path)


if __name__ == "__main__":
    main()
