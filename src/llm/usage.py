"""Ước tính số token và chi phí sử dụng OpenAI."""

from __future__ import annotations

import logging

import tiktoken
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from llm.client import get_chat_model

logger = logging.getLogger(__name__)

# (input, cached_input, output) USD/1M token - "cached_input" là giá của phần input token được
# OpenAI phục vụ từ prompt cache (usage.input_token_details.cache_read), rẻ hơn input thường vì
# input/output/cached input luôn có giá khác nhau, không thể lấy chung 1 giá input cho cả 2.
PRICING_PER_1M_TOKENS: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "o4-mini": (1.10, 0.275, 4.40),
}

# Embedding chỉ tính phí theo input token (không có output) - giá USD/1M token.
EMBEDDING_PRICING_PER_1M_TOKENS: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
) -> float | None:
    """Ước tính chi phí USD của một lượt gọi LLM dựa trên bảng giá PRICING_PER_1M_TOKENS.

    OpenAI thường trả về tên model kèm ngày snapshot (vd "gpt-4.1-mini-2025-04-14") nên
    khớp theo tiền tố dài nhất trong bảng giá thay vì khớp chính xác tuyệt đối. Phần
    cached_input_tokens (đã tính trong input_tokens, KHÔNG cộng thêm) được tính riêng theo giá
    cached input rẻ hơn - phần input còn lại mới tính theo giá input thường.

    Args:
        model: Tên model do OpenAI trả về (có thể kèm ngày snapshot).
        input_tokens: Tổng số token đầu vào (bao gồm cả phần cached).
        output_tokens: Số token đầu ra.
        cached_input_tokens: Số token đầu vào được phục vụ từ prompt cache (giá rẻ hơn).

    Returns:
        Chi phí ước tính (USD), hoặc None nếu không có giá cho model này.
    """
    pricing = PRICING_PER_1M_TOKENS.get(model)
    if pricing is None:
        matches = [alias for alias in PRICING_PER_1M_TOKENS if model.startswith(alias)]
        if matches:
            pricing = PRICING_PER_1M_TOKENS[max(matches, key=len)]
    if pricing is None:
        return None
    input_price, cached_input_price, output_price = pricing
    cached_input_tokens = min(cached_input_tokens, input_tokens)
    uncached_input_tokens = input_tokens - cached_input_tokens
    return (
        (uncached_input_tokens / 1_000_000) * input_price
        + (cached_input_tokens / 1_000_000) * cached_input_price
        + (output_tokens / 1_000_000) * output_price
    )


def estimate_embedding_usage(model: str, texts: list[str]) -> dict:
    """Ước tính usage (token + chi phí) cho một batch gọi embed_texts().

    OpenAI embeddings API (qua langchain_openai) không trả lại usage_metadata như chat
    model nên phải tự đếm token bằng tiktoken (không gọi thêm request nào, đếm cục bộ) rồi
    tính giá theo EMBEDDING_PRICING_PER_1M_TOKENS. Không chính xác tuyệt đối 100% (tiktoken
    là xấp xỉ cho model embedding, chính xác nhất cho model chat cùng họ) nhưng đủ tốt để
    ước lượng chi phí, hơn hẳn việc không track gì.

    Args:
        model: Tên model embedding (dùng để chọn encoding và giá).
        texts: Danh sách đoạn text sẽ được embed.

    Returns:
        dict gồm "input_tokens", "output_tokens" (luôn 0) và "cost_usd".
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    input_tokens = sum(len(encoding.encode(t)) for t in texts)

    pricing = EMBEDDING_PRICING_PER_1M_TOKENS.get(model)
    cost = (input_tokens / 1_000_000) * pricing if pricing is not None else None
    return {"input_tokens": input_tokens, "output_tokens": 0, "cost_usd": cost}


def sum_usage(*usages: dict | None) -> dict:
    """Gộp nhiều usage_info thành một tổng.

    Ví dụ 1 lượt chấm checklist có 2 lệnh LLM: generate_queries + evaluate. cost_usd nào
    là None (model không có giá trong bảng) thì bỏ qua khi cộng, chỉ trả None nếu TẤT CẢ
    đều None (không giả vờ biết chi phí khi thực ra không tính được).

    Args:
        *usages: Các dict usage_info (hoặc None) cần gộp.

    Returns:
        dict gồm "input_tokens", "output_tokens" và "cost_usd" đã gộp.
    """
    total_input = sum(u.get("input_tokens", 0) for u in usages if u)
    total_output = sum(u.get("output_tokens", 0) for u in usages if u)
    total_cached = sum(u.get("cached_input_tokens", 0) for u in usages if u)
    costs = [u["cost_usd"] for u in usages if u and u.get("cost_usd") is not None]
    total_cost = sum(costs) if costs else None
    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cached_input_tokens": total_cached,
        "cost_usd": total_cost,
    }


def invoke_structured_with_usage(model: str, system_prompt: str, user_content: str, schema: type[BaseModel]):
    """Điểm gọi LLM DUY NHẤT cho mọi lệnh trích xuất/đánh giá có structured output trong dự án.

    Domain module chỉ cần nạp prompt (utils.prompt_loader.load_prompt) + schema Pydantic của
    riêng mình rồi gọi hàm này với tên model (str) - không cần tự get_chat_model()/quản lý
    ChatOpenAI, tránh lặp lại logic khởi tạo model + with_structured_output(include_raw=True)
    + tính usage ở từng module (trước đây mỗi domain tự làm việc này).

    Args:
        model: Tên model OpenAI (vd từ config/settings.py, "gpt-4.1-mini") - được cache theo
            tên qua llm.client.get_chat_model, không tạo lại ChatOpenAI mỗi lần gọi.
        system_prompt: Nội dung system prompt.
        user_content: Nội dung message người dùng.
        schema: Lớp Pydantic mô tả structured output mong muốn.

    Returns:
        Tuple (parsed_object, usage_dict) - đối tượng đã parse theo schema và dict usage
        (input_tokens, output_tokens, cost_usd).

    Raises:
        RuntimeError: Khi LLM không trả về đối tượng hợp lệ theo schema.
    """
    chat_model = get_chat_model(model)
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
    cached_input_tokens = (usage.get("input_token_details") or {}).get("cache_read", 0)
    model_name = (getattr(raw_message, "response_metadata", None) or {}).get("model_name", "")

    cost = estimate_cost_usd(model_name, input_tokens, output_tokens, cached_input_tokens)
    usage_info = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cost_usd": cost,
    }
    logger.debug(
        "LLM usage model=%s, input_tokens=%s, cached_input_tokens=%s, output_tokens=%s, cost_usd=%s",
        model_name, input_tokens, cached_input_tokens, output_tokens, cost,
    )
    return parsed, usage_info
