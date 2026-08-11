"""Node 3: LLM đánh giá pass/fail dựa trên các Điều đã search - xem llm/checklist_evaluation.py."""

from __future__ import annotations

import logging

from llm.checklist_evaluation import evaluate_item
from rag.state import ChecklistItemState

logger = logging.getLogger(__name__)


def run(state: ChecklistItemState) -> dict:
    item_id = state["item"].get("id", "")
    evaluation, usage = evaluate_item(state["item"], state["clauses"])
    logger.info("Evaluate xong cho item_id=%s, status=%s", item_id, evaluation.status)
    return {"evaluation": evaluation, "usage": usage}
