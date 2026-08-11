"""Cấu hình logging dùng chung cho CLI scripts và app - đọc mức log từ LOG_LEVEL."""

from __future__ import annotations

import logging
import sys
import warnings

from config.settings import LOG_LEVEL

_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """Bật logging ra stdout, encoding UTF-8, format có timestamp + module. Gọi 1 lần ở entrypoint."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    # Docling khai báo 1 số Pydantic model có field tên "model_..." (vd model_impl, model_spec) -
    # trùng tiền tố protected namespace mặc định của Pydantic 2, chỉ là cảnh báo vô hại từ code
    # bên thứ ba (không sửa được), lọc bớt để log khởi động app không bị rác.
    warnings.filterwarnings(
        "ignore", message=r'Field "model_.*" in .* has conflict with protected namespace "model_"', category=UserWarning
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(level or LOG_LEVEL)
    root.addHandler(handler)

    _CONFIGURED = True
