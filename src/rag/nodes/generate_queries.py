"""Node 1: sinh truy vấn tìm kiếm đơn chủ đề từ mục checklist - xem llm/query_generation.py."""

from __future__ import annotations

import logging

from llm.query_generation import generate_search_queries
from rag.state import ChecklistItemState

logger = logging.getLogger(__name__)


def run(state: ChecklistItemState) -> dict:
    item_id = state["item"].get("id", "")
    queries, usage = generate_search_queries(state["item"])
    logger.info("Sinh truy vấn xong cho item_id=%s: %s", item_id, queries)
    return {"query_texts": queries, "query_generation_usage": usage}
