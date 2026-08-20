"""Tính accuracy tổng thể (status pass/fail) + retrieval trung bình cho 1 lượt chạy checklist so
với ground truth - xem evaluation/evaluate.py ở root cho cách dùng (CLI đọc file JSON, in báo cáo)."""

from __future__ import annotations

from checklist.evaluator import ChecklistEvaluator
from evaluation.metrics import accuracy
from evaluation.retrieval import retrieval_metrics

CONCLUSIVE_STATUSES = ChecklistEvaluator.CONCLUSIVE_STATUSES
normalize_status = ChecklistEvaluator.normalize_status


def evaluate(ground_truth: dict[str, dict], system_output: dict[str, dict]) -> dict:
    per_item = []
    for item_id, gt_item in ground_truth.items():
        gt = gt_item["ground_truth"]
        gt_status = normalize_status(gt["status"])
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
            sys_status = normalize_status(sys_item.get("status", ""))
            row["system_status"] = sys_status
            if gt_status in CONCLUSIVE_STATUSES:
                row["status_match"] = sys_status == gt_status
            # cited_clauses là danh sách Điều đã gộp (không phải Khoản phẳng) - ground truth cũng
            # chỉ liệt kê ở cấp Điều nên so khớp theo article_number là đủ và đúng.
            predicted_articles = [{"number": g.get("article_number", "")} for g in sys_item.get("cited_clauses", [])]
            row["retrieval"] = retrieval_metrics(predicted_articles, gt.get("relevant_clauses", []))

        per_item.append(row)

    conclusive = [r for r in per_item if r["ground_truth_status"] in CONCLUSIVE_STATUSES and not r["missing_in_system_output"]]
    status_accuracy = accuracy([r["status_match"] for r in conclusive])

    retrieval_rows = [r["retrieval"] for r in per_item if r["retrieval"] and r["retrieval"]["recall"] is not None]
    mean_recall = sum(r["recall"] for r in retrieval_rows) / len(retrieval_rows) if retrieval_rows else None
    mean_precision = sum(r["precision"] for r in retrieval_rows) / len(retrieval_rows) if retrieval_rows else None

    missing = [r["item_id"] for r in per_item if r["missing_in_system_output"]]

    return {
        "summary": {
            "total_items": len(per_item),
            "conclusive_items_evaluated": len(conclusive),
            "status_accuracy": round(status_accuracy, 3) if status_accuracy is not None else None,
            "mean_retrieval_recall": round(mean_recall, 3) if mean_recall is not None else None,
            "mean_retrieval_precision": round(mean_precision, 3) if mean_precision is not None else None,
            "missing_in_system_output": missing,
        },
        "items": per_item,
    }
