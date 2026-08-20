"""Hàm thống kê thuần dùng chung cho evaluation/retrieval.py và evaluation/checklist.py - tách
riêng để không lặp lại cùng 1 phép tính precision/recall/accuracy ở nhiều nơi."""

from __future__ import annotations


def precision_recall(n_hit: int, n_predicted: int, n_relevant: int) -> dict:
    """Precision/recall cổ điển - trả (None, None) nếu không có gì "relevant" để so (không thể tính
    recall có ý nghĩa), khớp hành vi gốc của evaluation/evaluate.py."""
    if n_relevant == 0:
        return {"recall": None, "precision": None}
    recall = n_hit / n_relevant
    precision = n_hit / n_predicted if n_predicted else 0.0
    return {"recall": round(recall, 3), "precision": round(precision, 3)}


def accuracy(matches: list[bool]) -> float | None:
    """Tỉ lệ True trong `matches` - None nếu rỗng (không có gì để tính, tránh chia 0)."""
    return sum(1 for m in matches if m) / len(matches) if matches else None
