"""State dùng chung giữa các node trong luồng chấm 1 mục checklist (rag/checklist_graph.py) -
tách riêng khỏi checklist_graph.py để mỗi node (rag/nodes/*.py) import được mà không phải import
ngược lại module lắp graph."""

from __future__ import annotations

from typing import Optional, TypedDict

from llm.checklist_evaluation import ClauseEvaluation


class ChecklistItemState(TypedDict):
    """Dữ liệu luân chuyển qua 3 node: generate_queries -> search -> evaluate."""

    contract_id: int
    item: dict
    query_texts: list[str]
    clauses: list[dict]
    evaluation: Optional[ClauseEvaluation]
    query_generation_usage: Optional[dict]
    usage: Optional[dict]
