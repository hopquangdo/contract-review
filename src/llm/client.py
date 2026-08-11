"""Cung cấp model ngôn ngữ dùng chung cho toàn ứng dụng."""

from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from config.settings import CHAT_MODEL, OPENAI_API_KEY

logger = logging.getLogger(__name__)

_chat_model: ChatOpenAI | None = None


def get_chat_model() -> ChatOpenAI:
    global _chat_model
    if _chat_model is None:
        logger.info("Khởi tạo chat model, model=%s", CHAT_MODEL)
        _chat_model = ChatOpenAI(model=CHAT_MODEL, api_key=OPENAI_API_KEY, temperature=0)
    return _chat_model
