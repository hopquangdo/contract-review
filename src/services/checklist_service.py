"""Nghiệp vụ chấm checklist cho 1 hợp đồng."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Iterator

from llm.usage import sum_usage
from rag.checklist_graph import evaluate_checklist_item, stream_checklist_item

logger = logging.getLogger(__name__)

_MAX_PARALLEL_ITEMS = 5


def _status_label(pass_status: bool) -> str:
    return "Đạt" if pass_status else "Không đạt"


def evaluate_single_item(
    contract_id: int, question: str, pass_criteria: str = "", violation_criteria: str = "", note: str = ""
) -> dict:
    item = {
        "id": "adhoc",
        "category": "",
        "question": question,
        "pass_criteria": pass_criteria,
        "violation_criteria": violation_criteria,
        "note": note,
        "severity": "medium",
        "needs_search": False,
    }
    logger.info("Bắt đầu đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)
    try:
        evaluation, clauses, usage = evaluate_checklist_item(contract_id, item)
    except Exception:
        logger.exception("Lỗi khi đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
        raise
    logger.info(
        "Hoàn tất đánh giá mục checklist đơn lẻ, contract_id=%s, status=%s, confidence=%s, "
        "evidence=%r, reason=%r, proposal=%r, n_clauses_cited=%d",
        contract_id, evaluation.status, evaluation.confidence,
        evaluation.evidence, evaluation.reason, evaluation.proposal, len(clauses),
    )

    return {
        "status": _status_label(evaluation.status == "pass"),
        "evidence": evaluation.evidence,
        "reasoning": evaluation.reason,
        "recommendation": evaluation.proposal,
        "confidence": evaluation.confidence,
        "clauses": clauses,
        "usage": usage,
    }


def _build_adhoc_item(question: str, pass_criteria: str, violation_criteria: str, note: str) -> dict:
    return {
        "id": "adhoc",
        "category": "",
        "question": question,
        "pass_criteria": pass_criteria,
        "violation_criteria": violation_criteria,
        "note": note,
        "severity": "medium",
        "needs_search": False,
    }


def stream_single_item(
    contract_id: int, question: str, pass_criteria: str = "", violation_criteria: str = "", note: str = ""
) -> Iterator[dict]:
    """Giống evaluate_single_item() nhưng phát ra từng bước (dict JSON-serializable được) NGAY
    khi node đó chạy xong - dùng cho API streaming (SSE), xem api/routes/checklist.py.

    Mỗi event có field "step" ("generate_queries"/"retrieval"/"evaluate") để frontend phân biệt,
    event "evaluate" là event CUỐI, có đầy đủ field giống evaluate_single_item() trả về."""
    item = _build_adhoc_item(question, pass_criteria, violation_criteria, note)
    logger.info("Bắt đầu STREAM đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)

    query_generation_usage = None
    clauses: list[dict] = []
    try:
        for node_name, partial_state in stream_checklist_item(contract_id, item):
            if node_name == "generate_queries":
                query_generation_usage = partial_state["query_generation_usage"]
                yield {"step": "generate_queries", "queries": partial_state["query_texts"]}
            elif node_name == "retrieval":
                clauses = partial_state["clauses"]  # giữ lại - node evaluate không trả lại "clauses"
                # (chỉ trả field nó thực sự đổi), cần nhớ từ bước này để đính kèm vào event cuối.
                yield {
                    "step": "retrieval",
                    "n_clauses": len(clauses),
                    "articles": [{"article_number": c["article_number"], "article_title": c["article_title"]} for c in clauses],
                }
            elif node_name == "evaluate":
                evaluation = partial_state["evaluation"]
                total_usage = sum_usage(query_generation_usage, partial_state["usage"])
                total_usage["duration_seconds"] = partial_state["duration_seconds"]
                logger.info(
                    "Hoàn tất STREAM đánh giá 1 mục checklist đơn lẻ, contract_id=%s, status=%s, confidence=%s",
                    contract_id, evaluation.status, evaluation.confidence,
                )
                yield {
                    "step": "evaluate",
                    "status": _status_label(evaluation.status == "pass"),
                    "evidence": evaluation.evidence,
                    "reasoning": evaluation.reason,
                    "recommendation": evaluation.proposal,
                    "confidence": evaluation.confidence,
                    "clauses": clauses,
                    "usage": total_usage,
                }
    except Exception:
        logger.exception("Lỗi khi STREAM đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
        yield {"step": "error", "message": "Đã xảy ra lỗi khi xử lý yêu cầu."}
        raise


def evaluate_checklist_batch(contract_id: int, items: list[dict]) -> list[dict]:
    def process_one(item: dict) -> dict:
        try:
            evaluation, clauses, _usage = evaluate_checklist_item(contract_id, item)
        except Exception:
            logger.exception(
                "Lỗi khi đánh giá mục checklist, contract_id=%s, item_id=%s", contract_id, item.get("id")
            )
            raise
        logger.info(
            "Chấm xong mục '%s' (item_id=%s), contract_id=%s, status=%s, evidence=%r, reason=%r, "
            "proposal=%r, n_clauses_cited=%d",
            item["question"], item["id"], contract_id, evaluation.status,
            evaluation.evidence, evaluation.reason, evaluation.proposal, len(clauses),
        )
        return {
            "item_id": item["id"],
            "category": item["category"],
            "question": item["question"],
            "status": evaluation.status,
            "evidence": evaluation.evidence,
            "reason": evaluation.reason,
            "proposal": evaluation.proposal,
            "cited_clauses": clauses,
        }

    logger.info("Bắt đầu chấm checklist hàng loạt, contract_id=%s, n_items=%d", contract_id, len(items))
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL_ITEMS) as executor:
        results = list(executor.map(process_one, items))
    n_pass = sum(1 for r in results if r["status"] == "pass")
    logger.info(
        "Hoàn tất chấm checklist hàng loạt, contract_id=%s, n_items=%d, n_pass=%d, n_fail=%d",
        contract_id, len(results), n_pass, len(results) - n_pass,
    )
    return results
