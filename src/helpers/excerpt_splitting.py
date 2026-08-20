"""Tách nội dung 1 Khoản dài thành nhiều Excerpt bằng LLM, nhóm theo Ý ngữ nghĩa thay vì cắt cứng
theo số thứ tự mục con (xem ingestion/excerpt_splitter.py - vẫn giữ làm fallback khi lệnh LLM lỗi,
để KHÔNG BAO GIỜ làm mất nội dung hợp đồng)."""

from __future__ import annotations

import logging

from config.settings import EXCERPT_SPLIT_MODEL
from ingestion.excerpt_splitter import _MAX_EXCERPT_CHARS, split_clause_into_excerpts as _split_regex
from llm.usage import invoke_structured_with_usage
from schema.excerpt_split import ExcerptSplit
from utils.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("excerpt_splitting_prompt.txt")


def split_clause_into_excerpts_llm(clause_text: str, max_chars: int = _MAX_EXCERPT_CHARS) -> tuple[list[str], dict | None]:
    """Tách 1 Khoản thành danh sách Excerpt, nhóm các mục con liên quan ngữ nghĩa (vd 2 lựa chọn
    nối bằng "và/hoặc", hay mục con phụ thuộc câu dẫn chung) vào cùng 1 Excerpt thay vì cắt cứng
    theo mọi mốc số thứ tự như ingestion.excerpt_splitter.

    Khoản đủ ngắn (<= max_chars) giữ nguyên hành vi cũ - không gọi LLM. Nếu lệnh LLM lỗi (network/
    parse), fallback về ingestion.excerpt_splitter (regex) - KHÔNG so khớp nguyên văn kết quả LLM
    với Khoản gốc (văn bản hợp đồng thực tế lẫn nhiều loại nhiễu parser - Commented [...], số thứ
    tự rác Docling... - liệt kê từng loại để validate không bao giờ phủ quát hết, và LLM tự lược
    bỏ đúng các loại nhiễu này là hành vi ĐÚNG, không phải hallucination).

    Args:
        clause_text: Nội dung 1 Khoản cần tách.
        max_chars: Ngân sách ký tự dưới đó bỏ qua bước LLM (Khoản đã đủ ngắn).

    Returns:
        Tuple (excerpts, usage_info) - usage_info là None nếu không gọi LLM (Khoản ngắn hoặc
        lệnh LLM lỗi phải fallback về regex).
    """
    if len(clause_text) <= max_chars:
        return [clause_text], None

    try:
        result, usage = invoke_structured_with_usage(EXCERPT_SPLIT_MODEL, _SYSTEM_PROMPT, clause_text, ExcerptSplit)
        excerpts = [e.text.strip() for e in result.excerpts if e.text.strip()]
        if excerpts:
            return excerpts, usage
        logger.warning("LLM tách Excerpt trả về danh sách rỗng - fallback về regex. len_clause=%d", len(clause_text))
    except Exception:
        logger.exception("Lỗi khi gọi LLM tách Excerpt - fallback về regex.")

    return _split_regex(clause_text, max_chars), None
