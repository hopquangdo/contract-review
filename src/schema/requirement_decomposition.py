"""Schema Pydantic cho kết quả phân rã 1 mục checklist thành yêu cầu - xem llm/requirement_decomposition.py."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementUnit(BaseModel):
    """1 yêu cầu (fact/điều kiện/chủ thể) riêng biệt cần xác minh, kèm truy vấn tìm kiếm của chính nó."""

    requirement: str = Field(description="1 điều kiện/fact/chủ thể riêng biệt cần xác minh.")
    queries: list[str] = Field(description="Truy vấn tìm kiếm cho đúng yêu cầu này - ít nhất 2 (nguyên văn + diễn giải).")


class RequirementDecomposition(BaseModel):
    """Danh sách yêu cầu phân rã ra từ 1 mục checklist."""

    requirements: list[RequirementUnit] = Field(description="Mỗi phần tử là 1 yêu cầu đơn chủ đề.")
