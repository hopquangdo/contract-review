"""State dùng chung giữa các node trong luồng chấm 1 mục checklist (checklist/workflow.py) - đặt trong
schema/ (không phải checklist/) để mỗi node (checklist/nodes.py) import được mà không phải
import ngược lại module lắp graph."""

from __future__ import annotations

from typing import Optional, TypedDict

from schema.evaluation import ClauseEvaluation
from schema.retrieval import MatchState, RawCandidate


class ChecklistItemState(TypedDict):
    """Dữ liệu luân chuyển qua 6 node: generate_queries -> retrieve -> rerank -> expand ->
    build_context -> evaluate.

    Attributes:
        contract_id: ID hợp đồng đang được chấm.
        item: Mục checklist gốc, tối thiểu có "id".
        requirements: Danh sách {"requirement": str, "queries": list[str]} - kết quả PHÂN RÃ DUY
            NHẤT (xem checklist/nodes.py::decompose_requirements), dùng chung cho retrieve (flatten "queries")
            và evaluate (nhận nguyên "requirement" làm khung xác minh, không tự phân rã lại).
        raw_candidates: Candidate THÔ (chưa chọn lọc) theo từng truy vấn con, do node retrieve điền
            - xem rag/retrieval.py::Retrieval.retrieve.
        match: Điểm/Điều cha của mọi Clause đã thấy (đã rerank nếu bật) + tập đã chọn, do node
            rerank điền - xem retrieval.py::Retrieval.rerank.
        top_numbers: Danh sách số hiệu Clause đã chọn (khớp trực tiếp), do node rerank điền.
        edges: Cạnh quan hệ đồ thị đã mở rộng được, do node expand điền - xem
            retrieval.py::Retrieval.expand.
        numbers_to_load: Toàn bộ số hiệu Clause cần lấy chi tiết (top_numbers + mở rộng), do node
            expand điền.
        clauses: Danh sách Điều khoản đã truy hồi (do node build_context điền), nhóm theo Điều cha.
        evidences: Cây quan hệ đồ thị đã dẫn tới từng Điều khoản khớp trực tiếp (do node
            build_context điền) - xem rag/builder.py::ContextBuilder.build_evidences.
        evaluation: Kết quả chấm pass/fail (do node evaluate điền), None trước khi node đó chạy.
        query_generation_usage: Chi phí LLM của node generate_queries, None trước khi node đó chạy.
        usage: Chi phí LLM của node evaluate, None trước khi node đó chạy.
    """

    contract_id: int
    item: dict
    requirements: list[dict]
    raw_candidates: dict[str, list[RawCandidate]]
    match: Optional[MatchState]
    top_numbers: list[str]
    edges: list[dict]
    numbers_to_load: list[str]
    clauses: list[dict]
    evidences: list[dict]
    evaluation: Optional[ClauseEvaluation]
    query_generation_usage: Optional[dict]
    usage: Optional[dict]
