"""Đánh giá 1 mục checklist dựa trên các Điều khoản liên quan của hợp đồng, và orchestration chạy
graph LangGraph đã compile ở checklist/workflow.py (xem đó cho cấu trúc 6 node:
generate_queries -> retrieve -> rerank -> expand -> build_context -> evaluate) - gộp cả phần gọi LLM
đánh giá (trước ở checklist/evaluator.py) lẫn phần entrypoint nghiệp vụ chạy graph (trước ở
checklist/runner.py) và quy tắc/hằng số quanh khái niệm "trạng thái" pass/fail (trước ở
checklist/rules.py, từng định nghĩa RIÊNG ở 2 nơi - services/checklist_service.py::_status_label và
evaluation/evaluate.py::_normalize_status/_CONCLUSIVE_STATUSES - gom về đây để không lệch nhau) vào
1 class vì đều xoay quanh CÙNG 1 khái niệm nghiệp vụ "chấm 1 mục checklist"."""

from __future__ import annotations

import logging
import re
import time
from typing import Iterator

from config.settings import EVALUATOR_MODEL
from schema.evaluation import ClauseEvaluation
from checklist import nodes
from checklist.workflow import build_item_graph
from llm.usage import invoke_structured_with_usage, sum_usage
from utils.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

# Dù prompt đã dặn "chỉ ghi số hiệu thô", LLM đôi khi vẫn kèm tiền tố nhãn ("Điều 11.1" thay vì
# "11.1") - chuẩn hoá lại ở code thay vì chỉ tin prompt tuân thủ tuyệt đối (đã quan sát LLM trả
# "Điều 0"/"Điều 12" trong khi key thật lưu là "0"/"12.1", khớp pattern phòng thủ đã dùng ở
# knowledge_graph/graph_extraction.py::_normalize_term).
_NUMBER_PREFIX_RE = re.compile(r"^\s*(Điều|Khoản|Phụ\s*lục)\s+", re.IGNORECASE)

# Bắt số hiệu Điều/Khoản được NHẮC TÊN trong "reason"/"proposal" (vd "sửa Điều 11.2", "theo Khoản
# 5.5.b" - chỉ bắt phần số "11.2"/"5.5", tự dừng trước ký tự không phải số như ".b"). Dù system
# prompt đã dặn (quy tắc 8) phải đồng bộ evidence_clause_numbers với các số hiệu được nhắc tên,
# KHÔNG tin tuyệt đối LLM tuân thủ 100% - quét lại bằng code để ĐẢM BẢO CHẮC CHẮN, xem
# ChecklistEvaluator._sync_evidence_numbers_with_text bên dưới.
_MENTION_RE = re.compile(r"(?:Điều|Khoản)\s+([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE)


class ChecklistEvaluator:
    """Chấm 1 mục checklist: gọi LLM đánh giá dựa trên Điều khoản liên quan (evaluate_item), tra
    ngược số hiệu evidence thành nội dung đầy đủ (resolve_evidence_clauses), và chạy graph
    generate_queries->retrieve->rerank->expand->build_context->evaluate (evaluate_checklist_item/
    stream_checklist_item/evaluate_checklist_item_with_requirements)."""

    # Trạng thái coi là "có kết luận rõ ràng" để tính accuracy pass/fail; các mục ground truth
    # no_info/not_applicable không có cách nào hệ thống "đoán đúng" nên loại khỏi accuracy, nhưng vẫn
    # được liệt kê riêng để biết hệ thống có tự nhận ra thiếu thông tin không.
    CONCLUSIVE_STATUSES = {"pass", "fail"}

    def __init__(self) -> None:
        self._system_prompt = load_prompt("checklist_evaluation_system_prompt.txt")
        self._item_graph = build_item_graph()

    def evaluate_checklist_item(self, contract_id: int, item: dict) -> tuple[ClauseEvaluation, list[dict], list[dict], dict]:
        """Chạy graph generate_queries -> retrieve -> rerank -> expand -> build_context -> evaluate cho
        1 mục checklist.

        usage_info trả về là TỔNG chi phí cả 2 lệnh LLM trong luồng (generate_queries + evaluate), gộp
        bằng llm.usage.sum_usage - các node retrieve/rerank/expand/build_context không gọi LLM (chỉ
        truy vấn Neo4j + tuỳ chọn cross-encoder rerank local/API riêng, không tính vào usage OpenAI này).

        Args:
            contract_id: ID hợp đồng cần chấm.
            item: Mục checklist gốc, tối thiểu có "id".

        Returns:
            Tuple (evaluation, clauses đã truy hồi, evidences, usage_info) - usage_info có thêm key
            "duration_seconds" là tổng thời gian chạy cả pipeline.
        """
        logger.debug(
            "Bắt đầu luồng generate_queries->retrieve->rerank->expand->build_context->evaluate cho "
            "item_id=%s, contract_id=%s", item.get("id", ""), contract_id,
        )
        start = time.perf_counter()
        final_state = self._item_graph.invoke(self._initial_state(contract_id, item))
        total_usage = sum_usage(final_state["query_generation_usage"], final_state["usage"])
        total_usage["duration_seconds"] = round(time.perf_counter() - start, 2)
        return final_state["evaluation"], final_state["clauses"], final_state["evidences"], total_usage

    def stream_checklist_item(self, contract_id: int, item: dict) -> Iterator[dict]:
        """Giống evaluate_checklist_item() nhưng phát TỪNG BƯỚC ngay khi node đó chạy xong, để UI hiện
        tiến trình trực tiếp (xem services/checklist_service.py::stream_single_item - nơi bọc thành sự
        kiện SSE cho frontend, tên "step" khớp đúng tên node: generate_queries/retrieve/evaluate...).

        Dùng _item_graph.stream(..., stream_mode="updates") của LangGraph - mỗi lần yield là 1 dict
        {tên_node: phần_state_node_đó_vừa_ghi}, không phải toàn bộ state - phải tự cộng dồn lại state
        đầy đủ qua các lần yield vì node evaluate cần "requirements"/"clauses" do các node TRƯỚC đã ghi.

        Args:
            contract_id: ID hợp đồng cần chấm.
            item: Mục checklist gốc, tối thiểu có "id".

        Yields:
            Tuple (node_name, state đầy đủ SAU KHI merge phần node đó vừa ghi) - node_name để bên gọi
            biết đây là bước nào (generate_queries/retrieve/rerank/expand/build_context/evaluate).
        """
        start = time.perf_counter()
        state = self._initial_state(contract_id, item)
        for update in self._item_graph.stream(state, stream_mode="updates"):
            node_name, delta = next(iter(update.items()))
            state.update(delta)
            if node_name == "evaluate":
                state["usage"] = sum_usage(state["query_generation_usage"], state["usage"])
                state["usage"]["duration_seconds"] = round(time.perf_counter() - start, 2)
            yield node_name, state

    def evaluate_checklist_item_with_requirements(
        self, contract_id: int, item: dict, requirements: list[dict]
    ) -> tuple[ClauseEvaluation, list[dict], list[dict], dict]:
        """Giống evaluate_checklist_item() nhưng BỎ QUA node generate_queries, dùng requirements có sẵn.

        Tiện test riêng retrieval/evaluate (đổi ngưỡng, thêm kênh tìm kiếm...) nhiều lần mà không tốn
        thời gian/chi phí phân rã lại mỗi lần chạy - phần phân rã vốn không đổi giữa các lần chỉ sửa
        retrieval/evaluate.

        Gọi TRỰC TIẾP các hàm run() của từng node (không qua LangGraph) vì đây là đường tắt chỉ dùng cho
        test/dev, không cần streaming hay khả năng mở rộng thêm node của graph đã compile.

        Args:
            contract_id: ID hợp đồng cần chấm.
            item: Mục checklist gốc, tối thiểu có "id".
            requirements: Danh sách yêu cầu đã phân rã sẵn (vd load từ file JSON do
                scripts/dump_requirements.py tạo trước), thay cho việc gọi lại LLM phân rã.

        Returns:
            Tuple (evaluation, clauses đã truy hồi, evidences, usage_info) - usage_info có thêm key
            "duration_seconds" là tổng thời gian chạy retrieve->rerank->expand->build_context->evaluate.
        """
        logger.debug(
            "Bắt đầu luồng retrieve->rerank->expand->build_context->evaluate (bỏ qua generate_queries) "
            "cho item_id=%s, contract_id=%s", item.get("id", ""), contract_id,
        )
        start = time.perf_counter()
        state: dict = {
            "contract_id": contract_id, "item": item, "requirements": requirements, "raw_candidates": {}, "match": None,
            "top_numbers": [], "edges": [], "numbers_to_load": [], "clauses": [], "evidences": [],
            "evaluation": None, "usage": None,
        }
        state.update(nodes.run_retrieve(state))
        state.update(nodes.run_rerank(state))
        state.update(nodes.run_expand(state))
        state.update(nodes.run_build_context(state))
        state.update(nodes.run_evaluate(state))
        total_usage = dict(state["usage"])
        total_usage["duration_seconds"] = round(time.perf_counter() - start, 2)
        return state["evaluation"], state["clauses"], state["evidences"], total_usage

    def evaluate_item(self, item: dict, requirements: list[dict], clause_groups: list[dict]) -> tuple[ClauseEvaluation, dict]:
        """Gọi LLM đánh giá 1 mục checklist dựa trên các Điều khoản liên quan đã truy hồi.

        Sau khi LLM trả kết quả, "status" được tính lại tất định bằng code thay vì tin trực
        tiếp field LLM tự viết, xem rationale ở phần thân hàm.

        Args:
            item: Mục checklist gốc (dict, tối thiểu có "id", "question").
            requirements: Danh sách yêu cầu ĐÃ PHÂN RÃ SẴN từ checklist/nodes.py::decompose_requirements
                (nguồn sự thật duy nhất cho "cần xác minh những gì" - dùng chung với bước
                retrieval). LLM ở đây CHỈ xác minh đúng và đủ từng yêu cầu đã cho, không tự
                phân rã lại (xem Bước 1 của system prompt).
            clause_groups: Danh sách Điều đã gộp sẵn từ
                rag.retrieval.Retrieval.run - mỗi phần tử có "text"
                gồm sẵn tiêu đề Điều + toàn bộ nội dung các Khoản con của Điều đó, không cần
                gắn nhãn số hiệu/tiêu đề riêng ở đây nữa.

        Returns:
            Tuple (evaluation, usage_info) - evaluation là ClauseEvaluation đã đánh giá,
            usage_info gồm input_tokens/output_tokens/cost_usd.

        Raises:
            Exception: Khi lời gọi LLM thất bại (được log rồi re-raise).
        """
        # "Các Điều khoản" (clauses_block) đặt TRƯỚC phần đặc thù của từng mục checklist (item JSON,
        # requirements) - dù cùng 1 hợp đồng nhưng khác câu hỏi checklist, tập Điều truy hồi thường
        # trùng lặp 1 phần (đặc biệt các Điều chung/định nghĩa hay được truy hồi lại). Đặt phần lớn +
        # có khả năng trùng lặp lên ĐẦU prompt (ngay sau phần dẫn cố định) để tối đa hoá tiền tố token
        # trùng khớp giữa các lượt gọi LLM khác nhau trên cùng hợp đồng - OpenAI chỉ cache theo TIỀN TỐ
        # tuyệt đối, phần thay đổi mỗi lượt (item/requirements) phải nằm ở CUỐI, không được đứng trước
        # phần dùng chung (xem group_by_article() ở rag/builder.py - nơi đảm bảo thứ tự Điều
        # trong clauses_block ổn định/theo số hiệu thay vì theo score, để "trùng lặp" này thực sự khớp
        # byte-for-byte chứ không chỉ trùng nội dung nhưng khác thứ tự).
        clauses_block = "\n\n---\n\n".join(g["text"] for g in clause_groups)
        requirements_block = "\n".join(f"- {r['requirement']}" for r in requirements)
        # Text phẳng (KHÔNG phải JSON) - chỉ giữ 4 trường LLM thực sự dùng (question/pass_criteria/
        # violation_criteria/note, đúng những gì system prompt tham chiếu, xem
        # llm/prompts/checklist_evaluation_system_prompt.txt). Bỏ id/category/severity/needs_search
        # (chỉ dùng nội bộ code - hiển thị UI/routing, LLM không cần) và khung JSON ("{", "}", dấu
        # ngoặc kép quanh mọi field) - giảm token input mà không đổi thông tin LLM nhận được.
        item_lines = [f"Question: {item['question']}"]
        if item.get("pass_criteria"):
            item_lines.append(f"Pass criteria: {item['pass_criteria']}")
        if item.get("violation_criteria"):
            item_lines.append(f"Violation criteria: {item['violation_criteria']}")
        if item.get("note"):
            item_lines.append(f"Note: {item['note']}")
        item_block = "\n".join(item_lines)
        user_content = (
            f"Các Điều khoản của hợp đồng được truy hồi (liên quan nhất tới mục checklist bên dưới):\n{clauses_block}\n\n"
            f"Mục checklist cần đánh giá:\n{item_block}\n\n"
            f"Danh sách yêu cầu cần xác minh (ĐÃ PHÂN RÃ SẴN - không tự phân rã lại, 1 verification_unit "
            f"cho MỖI yêu cầu dưới đây, không gộp/không bỏ sót):\n{requirements_block}\n\n"
            f"Hãy đánh giá hợp đồng dựa trên mục checklist trên."
        )
        logger.debug(
            "Gọi LLM đánh giá checklist item_id=%s, n_articles=%d, input_len=%d",
            item.get("id", ""), len(clause_groups), len(user_content),
        )
        try:
            result, usage = invoke_structured_with_usage(EVALUATOR_MODEL, self._system_prompt, user_content, ClauseEvaluation)
        except Exception:
            logger.exception("Lỗi khi gọi LLM đánh giá checklist item_id=%s", item.get("id", ""))
            raise
        result.item_id = item.get("id", "")

        valid_numbers = {c["number"] for g in clause_groups for c in g["clauses"]}
        self._sync_evidence_numbers_with_text(result, valid_numbers)

        # Tính lại "status" bằng code THAY VÌ tin trực tiếp field LLM tự viết - đã quan sát trường hợp
        # verification_units phân tích ĐÚNG (vd 1 unit "not_met") nhưng LLM vẫn tự ghi "status": "pass",
        # mâu thuẫn với chính phân tích của nó. Tính tất định từ dữ liệu có cấu trúc loại bỏ hẳn lớp lỗi
        # này, không tốn thêm lệnh LLM nào.
        llm_status = result.status
        any_not_met = any(u.result == "not_met" for u in result.verification_units)
        result.status = "fail" if (result.violates_prohibition or any_not_met) else "pass"
        if result.status != llm_status:
            logger.warning(
                "item_id=%s: status LLM tự viết (%s) mâu thuẫn với verification_units/violates_prohibition - "
                "đã ghi đè thành %s", item.get("id", ""), llm_status, result.status,
            )
        logger.debug("LLM trả về status=%s, usage=%s", result.status, usage)
        return result, usage

    def resolve_evidence_clauses(self, numbers: list[str], clause_groups: list[dict]) -> list[dict]:
        """Tra ngược số hiệu Điều/Khoản LLM trả về (evidence_clause_numbers - CHỈ số hiệu, không có
        nội dung, xem schema/evaluation.py::ClauseEvaluation) thành nội dung đầy đủ để hiển thị "Căn cứ"
        cho người dùng, mỗi Khoản 1 dòng - không tốn thêm token LLM viết lại nội dung.

        Args:
            numbers: Danh sách số hiệu LLM đã chọn làm căn cứ (vd ["11.1", "11.2"] hoặc "Điều 11.1" -
                được chuẩn hoá bỏ tiền tố trước khi tra, xem _normalize_clause_number).
            clause_groups: Danh sách Điều đã gộp sẵn (xem rag.builder.ContextBuilder.group_by_article)
                - mỗi Điều có "clauses" là danh sách Khoản con với number/title/text đầy đủ.

        Returns:
            Danh sách dict {"number", "title", "text", "article_number", "article_title", "is_appendix"}
            theo ĐÚNG thứ tự numbers - bỏ qua số hiệu không tìm thấy trong clause_groups (LLM có thể
            "ảo giác" số hiệu không tồn tại, không nên hiển thị 1 dòng rỗng cho người dùng).
            article_number/article_title/is_appendix để người dùng biết NGAY căn cứ này thuộc Điều
            hay Phụ lục nào (vd Khoản "PL03.1" tự nó không đủ rõ nếu không kèm "Phụ lục 03" - trước
            đây bị bỏ mất field này khi trả về, chỉ hiện được số hiệu Khoản con trơ trọi).
        """
        lookup = {c["number"]: c for g in clause_groups for c in g["clauses"]}
        resolved = []
        for raw_number in numbers:
            number = self._normalize_clause_number(raw_number)
            c = lookup.get(number)
            if c is None:
                logger.warning(
                    "evidence_clause_numbers chứa số hiệu không tồn tại trong clause_groups: %r (chuẩn hoá: %r)",
                    raw_number, number,
                )
                continue
            resolved.append({
                "number": c["number"],
                "title": c["title"],
                "text": c["text"],
                "article_number": c["article_number"],
                "article_title": c["article_title"],
                "is_appendix": c.get("is_appendix", False),
            })
        return resolved

    @staticmethod
    def status_label(is_pass: bool) -> str:
        """Đổi bool pass/fail thành nhãn tiếng Việt hiển thị cho người dùng."""
        return "Đạt" if is_pass else "Không đạt"

    @staticmethod
    def normalize_status(status: str) -> str:
        return status.strip().lower()

    def _initial_state(self, contract_id: int, item: dict) -> dict:
        """State khởi tạo cho _item_graph.invoke()/.stream() - mọi field bắt đầu rỗng/None, các node
        lần lượt điền vào theo đúng thứ tự phụ thuộc (xem schema/checklist_item_state.py)."""
        return {
            "contract_id": contract_id, "item": item, "requirements": [], "raw_candidates": {}, "match": None,
            "top_numbers": [], "edges": [], "numbers_to_load": [], "clauses": [], "evidences": [],
            "evaluation": None, "query_generation_usage": None, "usage": None,
        }

    def _sync_evidence_numbers_with_text(self, result: ClauseEvaluation, valid_numbers: set[str]) -> None:
        """Bổ sung vào evidence_clause_numbers mọi số hiệu THẬT SỰ TỒN TẠI (có trong valid_numbers) mà
        LLM có nhắc tên trong "reason"/"proposal" nhưng lại quên liệt kê vào evidence_clause_numbers -
        tránh tình trạng Recommendation nói "sửa Điều X" nhưng phần Căn cứ không có Điều X để bấm vào
        xem (KHÔNG thêm số hiệu không tồn tại - vd LLM đề xuất "thêm Khoản 5.6 mới" thì "5.6" chưa có
        thật trong valid_numbers nên tự động bị loại, không bị thêm nhầm)."""
        existing = set(result.evidence_clause_numbers)
        texts = [result.reason, *result.proposal]
        for text in texts:
            for m in _MENTION_RE.finditer(text or ""):
                num = m.group(1)
                if num in valid_numbers and num not in existing:
                    result.evidence_clause_numbers.append(num)
                    existing.add(num)
                    logger.info("Tự bổ sung evidence_clause_numbers=%r (được nhắc tên trong reason/proposal nhưng LLM bỏ sót)", num)

    def _normalize_clause_number(self, raw: str) -> str:
        return _NUMBER_PREFIX_RE.sub("", raw).strip()
