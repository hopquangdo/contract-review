"""Rerank candidate bằng cross-encoder model thật (không phải LLM prompt) - dùng sau vector search
để chấm lại độ liên quan query-candidate chính xác hơn cosine similarity thô của embedding (embedding
chỉ encode query/candidate ĐỘC LẬP rồi so cosine, cross-encoder encode CẢ CẶP cùng lúc nên bắt được
tương tác ngữ nghĩa tinh hơn, đổi lại chậm hơn nên chỉ áp dụng cho tập candidate đã thu hẹp qua vector
search, không thay thế nó)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from config.settings import RERANK_MODEL

logger = logging.getLogger(__name__)


class Reranker(ABC):
    """Cho phép đổi model/nhà cung cấp rerank mà không phải sửa nơi gọi."""

    @abstractmethod
    def score_pairs(self, query: str, texts: list[str]) -> list[float]:
        """Chấm độ liên quan của TỪNG text trong `texts` với `query`.

        Returns:
            Danh sách điểm số trong khoảng 0..1 (qua sigmoid), CÙNG THỨ TỰ với `texts` - điểm càng
            cao càng liên quan.
        """


class CrossEncoderReranker(Reranker):
    """Rerank bằng cross-encoder model local qua sentence-transformers (không cần API key)."""

    def __init__(self) -> None:
        from sentence_transformers import CrossEncoder

        logger.info("Khởi tạo CrossEncoder reranker, model=%s (tải lần đầu có thể mất vài phút)", RERANK_MODEL)
        self._model = CrossEncoder(RERANK_MODEL)

    def score_pairs(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        pairs = [(query, text) for text in texts]
        scores = self._model.predict(pairs, activation_fn=None)
        # activation_fn=None (mặc định model tự quyết định) không đảm bảo về đúng khoảng 0..1 với
        # mọi checkpoint - tự áp sigmoid ở đây để chắc chắn luôn có 1 thang điểm nhất quán, dễ đặt
        # ngưỡng RERANK_MIN_SCORE/RERANK_GAP_MARGIN (xem config/settings.py).
        import math

        return [1 / (1 + math.exp(-s)) for s in scores]


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    """Trả về Reranker dùng chung (singleton, cross-encoder local), khởi tạo (load model) nếu
    chưa có."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker
