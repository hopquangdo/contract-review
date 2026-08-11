"""Đánh giá 1 mục checklist dựa trên các Điều khoản liên quan của hợp đồng."""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from llm.client import get_chat_model
from llm.prompt_loader import load_prompt
from llm.usage import invoke_structured_with_usage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("checklist_evaluation_system_prompt.txt")


class VerificationUnit(BaseModel):
    """1 đơn vị cần xác minh riêng biệt (1 điều kiện/fact/chủ thể) trong pass_criteria/
    violation_criteria/note - xem Bước 1 của system prompt. Sinh TRƯỚC 'status' trong
    ClauseEvaluation để ép model xác minh xong xuôi từng đơn vị rồi mới được chốt kết luận, thay
    vì chốt kết luận trước rồi viết lý do biện minh ngược lại (rationalize)."""

    requirement: str = Field(description="1 đơn vị cần xác minh - 1 điều kiện/fact/chủ thể riêng biệt.")
    result: Literal["met", "not_met", "not_applicable"] = Field(
        description="'met' nếu có bằng chứng trực tiếp đáp ứng; 'not_applicable' nếu điều kiện kích "
        "hoạt yêu cầu này được xác nhận KHÔNG xảy ra/không tồn tại (nên yêu cầu không áp dụng); "
        "'not_met' cho mọi trường hợp còn lại (thiếu bằng chứng, mập mờ, hoặc điều kiện kích hoạt có "
        "xảy ra nhưng không đáp ứng yêu cầu đi kèm)."
    )
    basis: str = Field(description="Bằng chứng trực tiếp (trích dẫn/số Điều) hoặc lý do not_applicable/not_met.")


class ClauseEvaluation(BaseModel):
    """Kết luận đạt/không đạt cho 1 mục checklist, kèm căn cứ, lý do và đề xuất chỉnh sửa."""

    item_id: str = ""
    evidence: str = Field(description="Căn cứ trong các Điều khoản được cung cấp: trích dẫn nguyên văn hoặc số Điều.")
    verification_units: list[VerificationUnit] = Field(
        description="Xác minh TỪNG đơn vị đã xác định ở Bước 1 - 1 phần tử cho MỖI đơn vị, không gộp/bỏ sót."
    )
    reason: str = Field(description="Tóm tắt ngắn gọn mạch lý luận dẫn tới kết luận, dựa trên verification_units.")
    status: str = Field(description="'pass' hoặc 'fail' - CHỈ 2 giá trị, tổng hợp từ verification_units.")
    proposal: str = Field(description="Đề xuất chỉnh sửa nếu fail, hoặc xác nhận ngắn gọn nếu pass.")
    confidence: int = Field(ge=0, le=100, description="Điểm tin cậy của kết luận, 0-100.")


def evaluate_item(item: dict, clause_groups: list[dict]) -> tuple[ClauseEvaluation, dict]:
    """Trả về (evaluation, usage_info) - usage_info gồm input_tokens/output_tokens/cost_usd.

    clause_groups: danh sách Điều đã gộp sẵn từ retrieval.vector_retriever.retrieve_relevant_clauses
    - mỗi phần tử có "text" gồm sẵn tiêu đề Điều + toàn bộ nội dung các Khoản con của Điều đó,
    không cần gắn nhãn số hiệu/tiêu đề riêng ở đây nữa."""
    clauses_block = "\n\n---\n\n".join(g["text"] for g in clause_groups)
    user_content = (
        f"Mục checklist cần đánh giá (JSON):\n{json.dumps(item, ensure_ascii=False, indent=2)}\n\n"
        f"Các Điều khoản của hợp đồng được truy hồi (liên quan nhất tới mục này):\n{clauses_block}\n\n"
        f"Hãy đánh giá hợp đồng dựa trên mục checklist trên."
    )
    logger.debug(
        "Gọi LLM đánh giá checklist item_id=%s, n_articles=%d, input_len=%d",
        item.get("id", ""), len(clause_groups), len(user_content),
    )
    try:
        result, usage = invoke_structured_with_usage(get_chat_model(), _SYSTEM_PROMPT, user_content, ClauseEvaluation)
    except Exception:
        logger.exception("Lỗi khi gọi LLM đánh giá checklist item_id=%s", item.get("id", ""))
        raise
    result.item_id = item.get("id", "")
    logger.debug("LLM trả về status=%s, usage=%s", result.status, usage)
    return result, usage
