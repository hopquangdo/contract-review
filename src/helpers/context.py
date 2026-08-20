"""Hàm phụ THUẦN hỗ trợ ContextBuilder (rag/builder.py) - key sắp xếp số hiệu Khoản/Điều theo đúng
thứ tự văn bản gốc. Tách khỏi rag/builder.py để ContextBuilder chỉ còn các method thật sự thao tác
trên dữ liệu Clause/Điều."""

from __future__ import annotations


def clause_sort_key(number: str) -> list[int]:
    if number == "0":
        return [-1]
    try:
        return [int(p) for p in number.split(".")]
    except ValueError:
        return [10**9]  # số hiệu bất thường (không thuần số) - đẩy xuống cuối, không raise


def article_sort_key(number: str) -> tuple[int, list[int]]:
    """Key sắp xếp Điều/Phụ lục theo thứ tự văn bản gốc (Điều trước Phụ lục, tăng dần theo số hiệu) -
    KHÔNG theo độ liên quan/match score, xem ContextBuilder.group_by_article() cho lý do."""
    if number.startswith("PL"):
        digits = number[2:]
        try:
            return (1, [int(p) for p in digits.split(".")])
        except ValueError:
            return (1, [10**9])
    if number == "0":
        return (0, [-1])
    try:
        return (0, [int(p) for p in number.split(".")])
    except ValueError:
        return (0, [10**9])
