"""Node 2: retrieval (vector search + graph expansion) trên các truy vấn đã sinh ở node
generate_queries - xem rag/retrieval/vector_retriever.py.

Đặt tên "retrieval" (không phải "search") vì "search" dành riêng cho 1 tool khác ở phase sau,
tránh trùng tên gây nhầm lẫn."""

from __future__ import annotations

import logging

from rag.state import ChecklistItemState
from rag.retrieval.vector_retriever import retrieve_relevant_clauses

logger = logging.getLogger(__name__)


def run(state: ChecklistItemState) -> dict:
    item_id = state["item"].get("id", "")
    clauses = retrieve_relevant_clauses(state["contract_id"], state["query_texts"])
    logger.info(
        "Retrieval xong cho item_id=%s, contract_id=%s, n_clauses=%d",
        item_id, state["contract_id"], len(clauses),
    )
    return {"clauses": clauses}
