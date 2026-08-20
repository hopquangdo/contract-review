"""Cache đĩa (1 file JSON) cho kết quả đánh giá checklist - CHỈ để phát triển frontend không tốn
tiền/gian gọi lại LLM nhiều lần cho cùng 1 câu hỏi/hợp đồng đã chấm trước đó (xem
config/settings.py::CHECKLIST_EVAL_CACHE_ENABLED và services/checklist_service.py - nơi thực sự
đọc/ghi cache này). Không phải cache đúng nghĩa production (không tự invalidate khi hợp đồng/prompt
đổi) - chỉ nên bật lúc dev, xem docstring CHECKLIST_EVAL_CACHE_ENABLED."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "checklist_eval_cache.json"


class EvalCache:
    """Cache đĩa đơn giản, khởi tạo lười (nạp file JSON lần đọc/ghi đầu tiên), an toàn giữa các
    thread bằng 1 lock riêng của instance."""

    def __init__(self, path: Path = _CACHE_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None

    @staticmethod
    def make_key(*parts: object) -> str:
        """Sinh cache key ổn định từ các phần dữ liệu đầu vào (vd contract_id, question, tiêu chí)."""
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def get(self, key: str) -> Any | None:
        """Trả về giá trị đã cache cho key, hoặc None nếu chưa có (cache miss)."""
        with self._lock:
            return self._load().get(key)

    def set(self, key: str, value: Any) -> None:
        """Ghi 1 kết quả vào cache và lưu ngay ra đĩa (đơn giản, chấp nhận I/O mỗi lần ghi vì tần suất
        thấp - chỉ 1 lệnh LLM/mục checklist, không phải hot path)."""
        with self._lock:
            cache = self._load()
            cache[key] = value
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        if self._cache is None:
            if self._path.exists():
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("Đã nạp checklist eval cache, n_entries=%d", len(self._cache))
            else:
                self._cache = {}
        return self._cache


_eval_cache: EvalCache | None = None


def get_eval_cache() -> EvalCache:
    """Trả về instance EvalCache dùng chung (singleton) cho toàn ứng dụng, khởi tạo lười."""
    global _eval_cache
    if _eval_cache is None:
        _eval_cache = EvalCache()
    return _eval_cache
