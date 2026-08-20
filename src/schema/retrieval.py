"""Kiểu dữ liệu trung gian luân chuyển giữa các node retrieval trong checklist/nodes.py (retrieve -> rerank
-> expand -> build_context) - thay thế class `_MatchResult` cũ (vốn là 1 object Python tuỳ ý, không
đi qua LangGraph state được) bằng TypedDict để tương thích `graph.state.ChecklistItemState`. Gồm cả
kiểu dữ liệu mô tả cây "evidences" (quan hệ đồ thị đã dẫn từ mỗi Clause khớp trực tiếp tới các Clause
được kéo theo, xem rag/builder.py::ContextBuilder.build_evidences) - cùng thuộc luồng dữ liệu retrieval,
Evidence luôn dựng TỪ MatchState/RawCandidate đã có."""

from __future__ import annotations

from typing import TypedDict


class RawCandidate(TypedDict):
    """1 candidate CHƯA CHỌN LỌC từ vector search (bước retrieve) - trước khi rerank/áp ngưỡng."""

    number: str
    chunk_index: int
    article_number: str
    score: float
    content: str


class MatchState(TypedDict):
    """Điểm/Điều cha của mọi Clause đã thấy qua vector search (và rerank nếu bật) - tích luỹ xuyên
    suốt mọi truy vấn con, dùng lại ở các bước sau (expand, build_context) để không phải tra lại."""

    best_score_by_number: dict[str, float]
    article_number_by_number: dict[str, str]
    matched_score_by_chunk: dict[tuple[str, int], float]


class EvidenceNode(TypedDict, total=False):
    """1 node trong cây evidences - root không có "relation" (chỉ node con mới có, ghi loại quan hệ
    dẫn từ node cha tới nó)."""

    number: str
    title: str
    is_appendix: bool
    matched: bool
    score: float | None
    content: str
    relation: str
    children: list["EvidenceNode"]


class Evidence(TypedDict):
    """1 cây evidences, gốc là 1 Clause khớp trực tiếp (vector search hoặc rerank)."""

    root: EvidenceNode
    chain: list[EvidenceNode]
