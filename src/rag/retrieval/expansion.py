"""Chiến lược mở rộng tập Clause SAU KHI vector search đã chọn ra top-k - tách riêng khỏi
vector_retriever.py để thêm/đổi chiến lược trong tương lai (vd graph traversal qua
REFERS_TO/DEPENDS_ON/EXCEPTION_TO) không phải sửa logic truy hồi cốt lõi.

Mỗi chiến lược nhận vào (contract_id, danh sách Clause đã khớp) và trả về danh sách SỐ HIỆU
Clause cần lấy thêm - không tự lấy nội dung, vector_retriever.py lo phần đó."""

from __future__ import annotations

from knowledge_graph.client import get_graph
from knowledge_graph.queries import GET_CLAUSES_DEFINING_USED_TERMS, GET_RELATED_CLAUSE_NUMBERS, GET_SIBLING_CLAUSE_NUMBERS


def expand_to_full_article(contract_id: int, article_numbers: list[str]) -> list[str]:
    """Trả về số hiệu TẤT CẢ Khoản thuộc các Điều trong article_numbers.

    Dùng khi 1 Khoản khớp câu hỏi nhưng tự nó không đủ ngữ cảnh để hiểu trọn vẹn quy định (vd
    Khoản nêu điều kiện nhưng hệ quả nằm ở Khoản liền kề cùng Điều) - kéo theo cả Điều thay vì
    chỉ đúng Khoản đã khớp."""
    if not article_numbers:
        return []
    rows = get_graph().query(
        GET_SIBLING_CLAUSE_NUMBERS,
        params={"contract_id": contract_id, "article_numbers": sorted(set(article_numbers))},
    )
    return [r["number"] for r in rows]


# Từ khoá tiếng Việt gợi ý loại quan hệ chéo nên ưu tiên kéo thêm, ứng với các quan hệ đã trích
# xuất sẵn khi build graph (xem llm/graph_extraction.py, knowledge_graph/queries.py::CREATE_CLAUSE_RELATIONS).
# Heuristic đơn giản (substring match) - đủ dùng để THU HẸP loại traversal thay vì kéo mù mọi
# quan hệ, không cần thêm 1 lượt gọi LLM chỉ để phân loại câu hỏi.
_RELATION_KEYWORDS: dict[str, list[str]] = {
    "EXCEPTION_TO": ["ngoại lệ", "trừ khi", "trừ trường hợp", "loại trừ", "không áp dụng"],
    "DEPENDS_ON": ["điều kiện", "phụ thuộc", "trước khi", "sau khi", "căn cứ"],
    "REFERS_TO": ["tham chiếu", "dẫn chiếu", "theo quy định tại", "theo điều", "theo khoản"],
}


def classify_relevant_relations(query_texts: list[str]) -> list[str]:
    """Suy ra các loại quan hệ chéo (REFERS_TO/DEPENDS_ON/EXCEPTION_TO) đáng kéo thêm dựa trên từ
    khoá trong câu hỏi/tiêu chí - vd câu hỏi có "ngoại lệ" thì ưu tiên traversal qua EXCEPTION_TO
    thay vì kéo tất cả loại quan hệ (tránh loãng ngữ cảnh không liên quan)."""
    combined = " ".join(t.lower() for t in query_texts if t)
    relations = [rel for rel, keywords in _RELATION_KEYWORDS.items() if any(kw in combined for kw in keywords)]
    return relations


def expand_by_relations(contract_id: int, numbers: list[str], relation_types: list[str]) -> list[str]:
    """Trả về số hiệu Khoản liên quan tới 'numbers' qua các loại quan hệ chéo trong
    'relation_types' (không phân biệt chiều quan hệ - xem GET_RELATED_CLAUSE_NUMBERS)."""
    if not numbers or not relation_types:
        return []
    rows = get_graph().query(
        GET_RELATED_CLAUSE_NUMBERS,
        params={"contract_id": contract_id, "numbers": sorted(set(numbers)), "relation_types": relation_types},
    )
    return [r["number"] for r in rows]


def expand_by_definitions(contract_id: int, numbers: list[str]) -> list[str]:
    """Trả về số hiệu Khoản ĐỊNH NGHĨA các thuật ngữ mà 'numbers' có sử dụng (quan hệ USES_TERM ->
    Definition <- DEFINES) - không cần phân loại theo câu hỏi như expand_by_relations vì đây luôn
    là ngữ cảnh cần thiết để hiểu đúng thuật ngữ, không phụ thuộc loại câu hỏi."""
    if not numbers:
        return []
    rows = get_graph().query(
        GET_CLAUSES_DEFINING_USED_TERMS, params={"contract_id": contract_id, "numbers": sorted(set(numbers))}
    )
    return [r["number"] for r in rows]
