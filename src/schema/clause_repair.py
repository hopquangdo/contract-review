"""Schema Pydantic cho kết quả LLM sửa cục bộ 1 đoạn Clause bị nghi thiếu số hiệu Khoản con
(xem ingestion/section_splitter.py::_audit_missing_numbers và llm/clause_repair.py)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class RepairedSubClause(BaseModel):
    """1 Khoản con xác định lại được từ đoạn văn bản gốc bị nghi tách sai."""

    number: str = Field(description="Số hiệu Khoản con ĐÚNG theo văn bản gốc, vd '2.7'.")
    text: str = Field(description="Nội dung NGUYÊN VĂN của đúng Khoản con này, trích liên tục từ văn bản gốc.")


class ClauseRepairSplit(BaseModel):
    """Toàn bộ Khoản con tách lại được từ 1 đoạn văn bản gốc, theo đúng thứ tự xuất hiện."""

    sub_clauses: List[RepairedSubClause] = Field(default_factory=list)
