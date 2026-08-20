"""Schema Pydantic cho kết quả LLM tách 1 Khoản thành nhiều Excerpt (đơn vị embedding)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ExcerptSpan(BaseModel):
    """Một Excerpt - PHẢI là đoạn trích nguyên văn liên tục từ Khoản gốc, không diễn giải/tóm tắt."""

    text: str = Field(description="Đoạn trích NGUYÊN VĂN liên tục từ văn bản gốc, không thêm/bớt/diễn giải.")


class ExcerptSplit(BaseModel):
    """Toàn bộ Excerpt tách được từ 1 Khoản, theo đúng thứ tự xuất hiện trong văn bản gốc."""

    excerpts: List[ExcerptSpan] = Field(default_factory=list)
