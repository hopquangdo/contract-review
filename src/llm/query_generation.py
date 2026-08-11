"""Sinh danh sách truy vấn tìm kiếm ĐƠN CHỦ ĐỀ từ 1 mục checklist - tách các khái niệm khác nhau
trong question/pass_criteria/violation_criteria ra thành truy vấn riêng, tránh gộp chung 1 chuỗi
làm loãng tín hiệu vector search khi mục checklist chứa nhiều điều kiện thuộc chủ đề khác nhau
(vd "thẩm quyền ký kết" + "giá trị hợp đồng" - xem rag/retrieval/vector_retriever.py)."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from llm.client import get_chat_model
from llm.prompt_loader import load_prompt
from llm.usage import invoke_structured_with_usage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("query_generation_prompt.txt")


class SearchQueries(BaseModel):
    """Danh sách truy vấn tìm kiếm đơn chủ đề sinh ra từ 1 mục checklist."""

    queries: list[str] = Field(description="Mỗi phần tử là 1 truy vấn ngắn gọn, chỉ xoay quanh 1 khái niệm.")


def generate_search_queries(item: dict) -> tuple[list[str], dict]:
    """Trả về (queries, usage_info). Nếu LLM lỗi/trả rỗng, fallback về đúng 3 trường thô
    (question/pass_criteria/violation_criteria) - không để bước retrieval bị chặn hoàn toàn chỉ vì
    bước sinh truy vấn thất bại."""
    user_content = f"Mục checklist (JSON):\n{json.dumps(item, ensure_ascii=False, indent=2)}"
    try:
        result, usage = invoke_structured_with_usage(get_chat_model(), _SYSTEM_PROMPT, user_content, SearchQueries)
    except Exception:
        logger.exception("Lỗi khi sinh truy vấn cho item_id=%s - fallback về question/pass/violation thô", item.get("id", ""))
        return _fallback_queries(item), {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    queries = [q for q in result.queries if q and q.strip()]
    if not queries:
        logger.warning("LLM trả về danh sách truy vấn rỗng cho item_id=%s - fallback về question/pass/violation thô", item.get("id", ""))
        queries = _fallback_queries(item)
    logger.debug("Sinh truy vấn cho item_id=%s: %s", item.get("id", ""), queries)
    return queries, usage


def _fallback_queries(item: dict) -> list[str]:
    raw = [item["question"], item.get("pass_criteria", ""), item.get("violation_criteria", "")]
    return [q for q in raw if q and q.strip()]
