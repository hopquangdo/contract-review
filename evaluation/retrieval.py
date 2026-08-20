"""Đo chất lượng retrieval (precision/recall theo số hiệu Điều khoản) - so kết quả hệ thống trả về
với danh sách "relevant_clauses" trong ground truth (xem evaluation/evaluate.py ở root cho cách dùng)."""

from __future__ import annotations

import re

from evaluation.metrics import precision_recall


def extract_clause_number(text: str) -> str | None:
    """Rút số Điều đầu tiên từ chuỗi kiểu 'Điều 15.1' hay '15' -> '15'."""
    match = re.search(r"(\d+)", text)
    return match.group(1) if match else None


def normalize_clause_set(clauses: list[str]) -> set[str]:
    numbers = {extract_clause_number(c) for c in clauses}
    return {n for n in numbers if n is not None}


def retrieval_metrics(predicted_clauses: list[dict], relevant_clauses: list[str]) -> dict:
    """So khớp `predicted_clauses` (mỗi phần tử có "number") với `relevant_clauses` (danh sách chuỗi
    ground truth) theo SỐ ĐIỀU (không phân biệt Khoản con) - trả {"recall","precision","hit"}."""
    relevant_set = normalize_clause_set(relevant_clauses)
    predicted_set = normalize_clause_set([str(c.get("number", "")) for c in predicted_clauses])

    if not relevant_set:
        return {"recall": None, "precision": None, "hit": None}

    hit = relevant_set & predicted_set
    result = precision_recall(len(hit), len(predicted_set), len(relevant_set))
    result["hit"] = sorted(hit)
    return result
