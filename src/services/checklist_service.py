"""Nghiệp vụ chấm checklist cho 1 hợp đồng."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Iterator

from checklist.eval_cache import get_eval_cache
from checklist.evaluator import ChecklistEvaluator
from config.settings import CHECKLIST_EVAL_CACHE_ENABLED
from rag.retrieval import Retrieval

logger = logging.getLogger(__name__)

_MAX_PARALLEL_ITEMS = 5


class ChecklistService:
    """Nghiệp vụ chấm checklist cho 1 hợp đồng."""

    def __init__(self) -> None:
        self._evaluator = ChecklistEvaluator()

    def evaluate_single_item(
        self, contract_id: int, question: str, pass_criteria: str = "", violation_criteria: str = "", note: str = ""
    ) -> dict:
        """Đánh giá 1 mục checklist tuỳ ý (không thuộc checklist đã lưu) trên 1 hợp đồng.

        Args:
            contract_id: ID hợp đồng cần đánh giá.
            question: Câu hỏi/nội dung mục checklist.
            pass_criteria: Tiêu chí để coi là đạt (tuỳ chọn).
            violation_criteria: Tiêu chí để coi là vi phạm (tuỳ chọn).
            note: Ghi chú thêm cho mục checklist (tuỳ chọn).

        Returns:
            dict gồm "status" (nhãn tiếng Việt), "evidence_clauses" (danh sách {number, title, text} -
            nội dung ĐẦY ĐỦ từng Điều/Khoản dùng làm căn cứ, đã tra ngược từ số hiệu LLM trả về, xem
            checklist.evaluator.resolve_evidence_clauses), "reasoning", "recommendation", "confidence",
            "verification_units" (xác minh từng đơn vị pass/violation/note), "clauses" (điều khoản được
            trích dẫn), "evidences" (cây quan hệ đồ thị đã dẫn tới từng điều khoản khớp trực tiếp) và
            "usage" (chi phí LLM).
        """
        cache_key = get_eval_cache().make_key("single", contract_id, question, pass_criteria, violation_criteria, note)
        if CHECKLIST_EVAL_CACHE_ENABLED:
            cached = get_eval_cache().get(cache_key)
            if cached is not None:
                logger.info("Cache HIT đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
                return cached

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
            evaluation, clauses, evidences, usage = self._evaluator.evaluate_checklist_item(contract_id, item)
        except Exception:
            logger.exception("Lỗi khi đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
            raise
        logger.info(
            "Hoàn tất đánh giá mục checklist đơn lẻ, contract_id=%s, status=%s, confidence=%s, "
            "evidence_clause_numbers=%r, reason=%r, proposal=%r, n_clauses_cited=%d",
            contract_id, evaluation.status, evaluation.confidence,
            evaluation.evidence_clause_numbers, evaluation.reason, evaluation.proposal, len(clauses),
        )

        result = {
            "status": self._evaluator.status_label(evaluation.status == "pass"),
            "evidence_clauses": self._evaluator.resolve_evidence_clauses(evaluation.evidence_clause_numbers, clauses),
            "reasoning": evaluation.reason,
            "recommendation": evaluation.proposal,
            "confidence": evaluation.confidence,
            "verification_units": [u.model_dump() for u in evaluation.verification_units],
            "clauses": clauses,
            "evidences": evidences,
            "usage": usage,
        }
        if CHECKLIST_EVAL_CACHE_ENABLED:
            get_eval_cache().set(cache_key, result)
        return result

    def stream_single_item(
        self, contract_id: int, question: str, pass_criteria: str = "", violation_criteria: str = "", note: str = ""
    ) -> Iterator[dict]:
        """Giống evaluate_single_item() nhưng phát TỪNG BƯỚC ngay khi xong (generate_queries/retrieval/
        evaluate), để UI hiện tiến trình trực tiếp thay vì đợi cả pipeline chạy xong mới thấy gì (xem
        api/routes/checklist.py::checklist_item_stream - route bọc kết quả này thành SSE).

        Chỉ phát 3 "step" mà frontend đọc (khớp type TraceEvent trong frontend/src/types.ts) - các node
        retrieve/rerank/expand nội bộ của pipeline (checklist/workflow.py) không có ý nghĩa
        hiển thị riêng với người dùng cuối nên gộp im lặng, chỉ báo khi build_context (bước retrieval
        cuối cùng, đã có đủ danh sách Điều) và evaluate xong.

        Args:
            contract_id: ID hợp đồng cần đánh giá.
            question: Câu hỏi/nội dung mục checklist.
            pass_criteria: Tiêu chí để coi là đạt (tuỳ chọn).
            violation_criteria: Tiêu chí để coi là vi phạm (tuỳ chọn).
            note: Ghi chú thêm cho mục checklist (tuỳ chọn).

        Yields:
            dict theo đúng 1 trong các dạng TraceEvent: {"step": "generate_queries", "queries": [...]},
            {"step": "retrieval", "n_clauses": int, "articles": [...]}, hoặc {"step": "evaluate", ...
            (toàn bộ SingleAnswer)}. Lỗi giữa chừng phát {"step": "error", "message": str} rồi dừng.
        """
        cache_key = get_eval_cache().make_key("stream", contract_id, question, pass_criteria, violation_criteria, note)
        if CHECKLIST_EVAL_CACHE_ENABLED:
            cached_events = get_eval_cache().get(cache_key)
            if cached_events is not None:
                logger.info("Cache HIT stream đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
                yield from cached_events
                return

        item = {
            "id": "adhoc", "category": "", "question": question, "pass_criteria": pass_criteria,
            "violation_criteria": violation_criteria, "note": note, "severity": "medium", "needs_search": False,
        }
        logger.info("Bắt đầu stream đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)
        events: list[dict] = []
        try:
            for node_name, state in self._evaluator.stream_checklist_item(contract_id, item):
                if node_name == "generate_queries":
                    queries = [q for r in state["requirements"] for q in r["queries"]]
                    event = {"step": "generate_queries", "queries": queries}
                elif node_name == "build_context":
                    articles = [
                        {"article_number": g["article_number"], "article_title": g["article_title"]}
                        for g in state["clauses"]
                    ]
                    event = {"step": "retrieval", "n_clauses": len(state["clauses"]), "articles": articles}
                elif node_name == "evaluate":
                    evaluation = state["evaluation"]
                    event = {
                        "step": "evaluate",
                        "status": self._evaluator.status_label(evaluation.status == "pass"),
                        "evidence_clauses": self._evaluator.resolve_evidence_clauses(evaluation.evidence_clause_numbers, state["clauses"]),
                        "reasoning": evaluation.reason,
                        "recommendation": evaluation.proposal,
                        "confidence": evaluation.confidence,
                        "verification_units": [u.model_dump() for u in evaluation.verification_units],
                        "clauses": state["clauses"],
                        "evidences": state["evidences"],
                        "usage": state["usage"],
                    }
                else:
                    continue
                events.append(event)
                yield event
        except Exception as e:
            logger.exception("Lỗi khi stream đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
            yield {"step": "error", "message": str(e)}
            return
        logger.info("Hoàn tất stream đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
        if CHECKLIST_EVAL_CACHE_ENABLED:
            get_eval_cache().set(cache_key, events)

    def evaluate_checklist_batch(self, contract_id: int, items: list[dict]) -> list[dict]:
        """Chấm toàn bộ checklist (nhiều mục) trên 1 hợp đồng, chạy song song tối đa
        _MAX_PARALLEL_ITEMS mục cùng lúc để giảm thời gian chờ.

        Args:
            contract_id: ID hợp đồng cần chấm.
            items: Danh sách mục checklist, mỗi mục là dict theo schema checklist item
                (id, category, question, ...).

        Returns:
            Danh sách kết quả đánh giá tương ứng từng mục (giữ nguyên thứ tự items), mỗi kết quả
            gồm item_id, category, question, status, evidence_clauses (danh sách {number, title, text}
            - nội dung đầy đủ, xem checklist.evaluator.resolve_evidence_clauses), reason, proposal,
            confidence, verification_units, cited_clauses, evidences (cây quan hệ đồ thị).
        """
        def process_one(item: dict) -> dict:
            cache_key = get_eval_cache().make_key("batch", contract_id, item["id"])
            if CHECKLIST_EVAL_CACHE_ENABLED:
                cached = get_eval_cache().get(cache_key)
                if cached is not None:
                    logger.info("Cache HIT mục checklist item_id=%s, contract_id=%s", item["id"], contract_id)
                    return cached
            try:
                evaluation, clauses, evidences, _usage = self._evaluator.evaluate_checklist_item(contract_id, item)
            except Exception:
                logger.exception(
                    "Lỗi khi đánh giá mục checklist, contract_id=%s, item_id=%s", contract_id, item.get("id")
                )
                raise
            logger.info(
                "Chấm xong mục '%s' (item_id=%s), contract_id=%s, status=%s, evidence_clause_numbers=%r, "
                "reason=%r, proposal=%r, n_clauses_cited=%d",
                item["question"], item["id"], contract_id, evaluation.status,
                evaluation.evidence_clause_numbers, evaluation.reason, evaluation.proposal, len(clauses),
            )
            result = {
                "item_id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "status": evaluation.status,
                "evidence_clauses": self._evaluator.resolve_evidence_clauses(evaluation.evidence_clause_numbers, clauses),
                "reason": evaluation.reason,
                "proposal": evaluation.proposal,
                "confidence": evaluation.confidence,
                "verification_units": [u.model_dump() for u in evaluation.verification_units],
                "cited_clauses": clauses,
                "evidences": evidences,
            }
            if CHECKLIST_EVAL_CACHE_ENABLED:
                get_eval_cache().set(cache_key, result)
            return result

        logger.info("Bắt đầu chấm checklist hàng loạt, contract_id=%s, n_items=%d", contract_id, len(items))
        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_PARALLEL_ITEMS) as executor:
            results = list(executor.map(process_one, items))
        n_pass = sum(1 for r in results if r["status"] == "pass")
        logger.info(
            "Hoàn tất chấm checklist hàng loạt, contract_id=%s, n_items=%d, n_pass=%d, n_fail=%d",
            contract_id, len(results), n_pass, len(results) - n_pass,
        )
        return results

    def get_similar_clauses(
        self, contract_id: int, clause_number: str, top_k: int = 5, same_type_only: bool = True,
    ) -> list[dict]:
        """Tìm các Điều khoản tương tự nội dung ở các hợp đồng KHÁC, để reviewer tham khảo chỉnh sửa
        lại 1 Điều khoản. Xem rag.retrieval.Retrieval.find_similar_clauses().

        Args:
            contract_id: ID hợp đồng chứa Điều khoản nguồn.
            clause_number: Số hiệu Điều khoản nguồn.
            top_k: Số lượng kết quả tối đa.
            same_type_only: True thì chỉ xét Điều khoản cùng ClauseType với Điều khoản nguồn.

        Returns:
            Danh sách dict {contract_id, contract_name, number, title, text, score}.
        """
        logger.info(
            "Bắt đầu tìm Clause tương tự, contract_id=%s, clause_number=%s, same_type_only=%s",
            contract_id, clause_number, same_type_only,
        )
        try:
            results = Retrieval(contract_id).find_similar_clauses(clause_number, top_k, same_type_only)
        except Exception:
            logger.exception(
                "Lỗi khi tìm Clause tương tự, contract_id=%s, clause_number=%s", contract_id, clause_number
            )
            raise
        logger.info(
            "Hoàn tất tìm Clause tương tự, contract_id=%s, clause_number=%s, n_found=%d",
            contract_id, clause_number, len(results),
        )
        return results
