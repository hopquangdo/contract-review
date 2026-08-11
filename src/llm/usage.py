"""Ước tính số token và chi phí sử dụng OpenAI."""

from __future__ import annotations

import logging

import tiktoken
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PRICING_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "o4-mini": (1.10, 4.40),
}

# Embedding chỉ tính phí theo input token (không có output) - giá USD/1M token.
EMBEDDING_PRICING_PER_1M_TOKENS: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Trả về None nếu không có giá cho model này. OpenAI thường trả về model kèm ngày
    snapshot (vd "gpt-4.1-mini-2025-04-14") nên khớp theo tiền tố dài nhất."""
    pricing = PRICING_PER_1M_TOKENS.get(model)
    if pricing is None:
        matches = [alias for alias in PRICING_PER_1M_TOKENS if model.startswith(alias)]
        if matches:
            pricing = PRICING_PER_1M_TOKENS[max(matches, key=len)]
    if pricing is None:
        return None
    input_price, output_price = pricing
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price


def estimate_embedding_usage(model: str, texts: list[str]) -> dict:
    """Ước tính usage cho 1 batch embed_texts() - OpenAI embeddings API (qua langchain_openai)
    không trả lại usage_metadata như chat model nên phải tự đếm token bằng tiktoken (không gọi
    thêm request nào, đếm cục bộ) rồi tính giá theo EMBEDDING_PRICING_PER_1M_TOKENS. Không chính
    xác tuyệt đối 100% (tiktoken là xấp xỉ cho model embedding, chính xác nhất cho model chat cùng
    họ) nhưng đủ tốt để ước lượng chi phí, hơn hẳn việc không track gì."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    input_tokens = sum(len(encoding.encode(t)) for t in texts)

    pricing = EMBEDDING_PRICING_PER_1M_TOKENS.get(model)
    cost = (input_tokens / 1_000_000) * pricing if pricing is not None else None
    return {"input_tokens": input_tokens, "output_tokens": 0, "cost_usd": cost}


def sum_usage(*usages: dict | None) -> dict:
    """Gộp nhiều usage_info (vd 1 lượt chấm checklist giờ có 2 lệnh LLM: generate_queries +
    evaluate) thành 1 tổng - cost_usd nào là None (model không có giá trong bảng) thì bỏ qua khi
    cộng, chỉ trả None nếu TẤT CẢ đều None (không giả vờ biết chi phí khi thực ra không tính được)."""
    total_input = sum(u.get("input_tokens", 0) for u in usages if u)
    total_output = sum(u.get("output_tokens", 0) for u in usages if u)
    costs = [u["cost_usd"] for u in usages if u and u.get("cost_usd") is not None]
    total_cost = sum(costs) if costs else None
    return {"input_tokens": total_input, "output_tokens": total_output, "cost_usd": total_cost}


def invoke_structured_with_usage(chat_model, system_prompt: str, user_content: str, schema: type[BaseModel]):
    """Giống llm.checklist_evaluation's structured_model.invoke(...) nhưng dùng
    include_raw=True để lấy thêm usage_metadata - trả về (parsed_object, usage_dict)."""
    structured_model = chat_model.with_structured_output(schema, include_raw=True)
    try:
        raw_result = structured_model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]
        )
    except Exception:
        logger.exception("Lỗi khi gọi LLM structured output cho schema %s", schema.__name__)
        raise
    parsed = raw_result.get("parsed")
    if not isinstance(parsed, schema):
        logger.error("LLM không trả về %s hợp lệ", schema.__name__)
        raise RuntimeError(f"LLM không trả về {schema.__name__} hợp lệ.")

    raw_message = raw_result.get("raw")
    usage = getattr(raw_message, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    model_name = (getattr(raw_message, "response_metadata", None) or {}).get("model_name", "")

    cost = estimate_cost_usd(model_name, input_tokens, output_tokens)
    usage_info = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
    }
    logger.debug(
        "LLM usage model=%s, input_tokens=%s, output_tokens=%s, cost_usd=%s",
        model_name, input_tokens, output_tokens, cost,
    )
    return parsed, usage_info
