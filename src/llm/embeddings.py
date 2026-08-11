"""Cung cấp embedding văn bản dùng chung cho toàn ứng dụng."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from config.settings import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, OPENAI_API_KEY

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Cho phép đổi nhà cung cấp embedding mà không phải sửa nơi gọi."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed nhiều đoạn text cùng lúc (batch) - dùng khi build graph cho toàn bộ Excerpt."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed 1 câu truy vấn - dùng khi retrieval cho 1 mục checklist."""

    @abstractmethod
    def as_langchain_embeddings(self) -> Embeddings:
        """Đối tượng Embeddings chuẩn LangChain - dùng cho tích hợp cần kiểu này (vd Neo4jVector),
        không lộ ra ngoài interface embed_texts/embed_query cho các nơi gọi thông thường."""


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Sinh vector embedding bằng API OpenAI."""

    def __init__(self) -> None:
        self._client = OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=OPENAI_API_KEY, dimensions=EMBEDDING_DIMENSIONS)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        logger.debug("Embed batch %d đoạn text (model=%s)", len(texts), EMBEDDING_MODEL)
        try:
            result = self._client.embed_documents(texts)
        except Exception:
            logger.exception("Lỗi khi embed batch %d đoạn text", len(texts))
            raise
        return result

    def embed_query(self, text: str) -> list[float]:
        logger.debug("Embed 1 câu truy vấn, len=%d (model=%s)", len(text), EMBEDDING_MODEL)
        try:
            return self._client.embed_query(text)
        except Exception:
            logger.exception("Lỗi khi embed câu truy vấn")
            raise

    def as_langchain_embeddings(self) -> Embeddings:
        return self._client


_embeddings: EmbeddingProvider | None = None


def get_embeddings() -> EmbeddingProvider:
    global _embeddings
    if _embeddings is None:
        logger.info("Khởi tạo embedding provider, model=%s", EMBEDDING_MODEL)
        _embeddings = OpenAIEmbeddingProvider()
    return _embeddings
