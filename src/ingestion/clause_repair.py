"""Sửa cục bộ 1 đoạn Clause bị nghi thiếu số hiệu Khoản con - xem
ingestion/section_splitter.py::_audit_missing_numbers (nguồn phát hiện DUY NHẤT, module này chỉ
sửa CỤ THỂ đúng đoạn đã bị chỉ ra, không tự quét/dọn toàn văn bản)."""

from __future__ import annotations

import logging
import re

from config.settings import EXCERPT_SPLIT_MODEL
from llm.usage import invoke_structured_with_usage
from schema.clause_repair import ClauseRepairSplit
from utils.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("clause_repair_prompt.txt")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    return _WHITESPACE_RE.sub("", text)


def repair_clause_span(clause_text: str, missing_numbers: list[str]) -> list[dict] | None:
    """Gọi LLM xác định lại ranh giới Khoản con ĐÚNG cho 1 đoạn Clause bị nghi thiếu số hiệu.

    Đoạn văn bản đưa vào LUÔN nhỏ (đúng 1 Clause cha, không phải cả Điều/toàn văn bản) nên có thể
    validate NGUYÊN VĂN chặt chẽ - khác hẳn helpers/excerpt_splitting.py (áp dụng cho đoạn dài, lẫn
    nhiều loại nhiễu parser không thể validate tuyệt đối). Chỉ trả kết quả khi validate PASS; mọi
    trường hợp còn lại (lỗi gọi LLM, validate fail) trả None để nơi gọi giữ nguyên hành vi cũ (an
    toàn, không mất dữ liệu).

    Args:
        clause_text: Nội dung 1 Clause cha bị nghi chứa số hiệu Khoản con bị thiếu.
        missing_numbers: Số hiệu Khoản con audit nghi thiếu bên trong clause_text (chỉ để gợi ý
            trong prompt, không dùng để validate cứng).

    Returns:
        Danh sách dict {"number", "text"} theo đúng thứ tự trong văn bản, hoặc None nếu không sửa
        được (giữ nguyên clause_text như 1 Clause duy nhất).
    """
    user_content = (
        f"Số hiệu nghi bị thiếu: {missing_numbers}\n\nĐoạn văn bản cần xác định lại ranh giới Khoản con:\n\n{clause_text}"
    )
    try:
        result, usage = invoke_structured_with_usage(EXCERPT_SPLIT_MODEL, _SYSTEM_PROMPT, user_content, ClauseRepairSplit)
    except Exception:
        logger.exception("Lỗi khi gọi LLM sửa Clause span, missing_numbers=%s", missing_numbers)
        return None

    sub_clauses = [{"number": s.number.strip(), "text": s.text.strip()} for s in result.sub_clauses if s.text.strip()]
    if not sub_clauses:
        return None

    joined = "".join(s["text"] for s in sub_clauses)
    if _normalize_ws(joined) != _normalize_ws(clause_text):
        logger.warning(
            "LLM sửa Clause span không khớp nguyên văn đoạn gốc - bỏ qua, giữ nguyên hành vi cũ. "
            "missing_numbers=%s, n_sub_clauses=%d", missing_numbers, len(sub_clauses),
        )
        return None

    logger.info(
        "LLM sửa Clause span thành công: %s -> %d Khoản con %s, usage=%s",
        missing_numbers, len(sub_clauses), [s["number"] for s in sub_clauses], usage,
    )
    return sub_clauses
