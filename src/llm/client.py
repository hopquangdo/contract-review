"""Cung cấp model ngôn ngữ dùng chung cho toàn ứng dụng.

Cache theo TÊN MODEL (không phải 1 singleton duy nhất), vì các bước khác nhau (build
graph/sinh truy vấn/đánh giá) có thể cấu hình model khác nhau qua .env (xem
GRAPH_EXTRACTION_MODEL/QUERY_GENERATION_MODEL/EVALUATOR_MODEL trong config/settings.py) -
đổi model cho 1 bước không ảnh hưởng các bước còn lại.

Theo cùng khuôn mẫu ABC + concrete provider + factory hàm module-level đã dùng ở llm/embeddings.py -
cho phép đổi nhà cung cấp chat model mà không phải sửa nơi gọi.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from langchain_openai import ChatOpenAI

from config.settings import BASE_URL, LLM_API_KEY

logger = logging.getLogger(__name__)


class ChatModelProvider(ABC):
    """Cho phép đổi nhà cung cấp chat model mà không phải sửa nơi gọi."""

    @abstractmethod
    def get_chat_model(self, model: str) -> ChatOpenAI:
        """Trả về chat model tương ứng với `model` (dùng lại nếu đã khởi tạo trước đó)."""


class OpenAIChatModelProvider(ChatModelProvider):
    """Cung cấp ChatOpenAI, cache theo tên model."""

    def __init__(self) -> None:
        self._chat_models: dict[str, ChatOpenAI] = {}

    def get_chat_model(self, model: str) -> ChatOpenAI:
        """Trả về ChatOpenAI đã cache theo tên model, khởi tạo mới nếu chưa có.

        Đọc LLM_API_KEY + BASE_URL (xem config/settings.py) - đổi nhà cung cấp (OpenAI/OpenRouter/Azure/
        tự host...) chỉ cần đổi 2 biến env này, không cần sửa code. BASE_URL=None thì ChatOpenAI tự dùng
        thẳng endpoint chính chủ của OpenAI.

        Args:
            model: Tên model (vd "gpt-4.1-mini", hoặc tên model của nhà cung cấp đang trỏ tới qua BASE_URL).

        Returns:
            Instance ChatOpenAI tương ứng với model (dùng lại nếu đã khởi tạo trước đó).
        """
        if model not in self._chat_models:
            logger.info("Khởi tạo chat model, model=%s, base_url=%s", model, BASE_URL or "(mặc định OpenAI)")
            self._chat_models[model] = ChatOpenAI(model=model, api_key=LLM_API_KEY, base_url=BASE_URL, temperature=0)
        return self._chat_models[model]


_chat_model_provider: ChatModelProvider | None = None


def get_chat_model(model: str) -> ChatOpenAI:
    """Trả về ChatOpenAI dùng chung (qua ChatModelProvider singleton), khởi tạo provider nếu chưa có.

    Args:
        model: Tên model (vd "gpt-4.1-mini", hoặc tên model của nhà cung cấp đang trỏ tới qua BASE_URL).

    Returns:
        Instance ChatOpenAI tương ứng với model (dùng lại nếu đã khởi tạo trước đó).
    """
    global _chat_model_provider
    if _chat_model_provider is None:
        _chat_model_provider = OpenAIChatModelProvider()
    return _chat_model_provider.get_chat_model(model)
