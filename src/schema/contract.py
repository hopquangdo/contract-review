"""Schema Pydantic cấp Hợp đồng (Agreement) - tương ứng cấu trúc graph sau:

Graph Structure
Agreement
   |
   ├── HAS_PARTY ───────► Organization
   |
   ├── HAS_SECTION ─────► Section
   │                         |
   │                         └── HAS_CLAUSE ──► Clause
   │                                             |
   │                                             ├── HAS_EXCERPT ──► Excerpt
   │                                             ├── HAS_TYPE ─────► ClauseType
   │                                             ├── REFERS_TO ────► Clause
   │                                             ├── DEPENDS_ON ───► Clause
   │                                             ├── EXCEPTION_TO ─► Clause
   │                                             ├── REFERS_TO_APPENDIX ► Clause (is_appendix=true)
   │                                             ├── DEFINES ──────► Definition
   │                                             └── USES_TERM ────► Definition
   |
   ├── GOVERNED_BY ─────► GoverningLaw
   |
   └── HAS_DISPUTE_RULE ► DisputeResolution

Phần schema cấp Điều khoản (Clause/Section/ClauseRelations/Definition) nằm ở schema/clause.py."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from schema.clause import ClauseRelations


class Party(BaseModel):
    """Danh tính và vai trò của 1 bên tham gia ký kết hợp đồng."""

    name: str
    role: str


class GoverningLaw(BaseModel):
    """Luật và thẩm quyền tài phán được hợp đồng viện dẫn để áp dụng."""

    country: str = ""
    state: str = ""


class DisputeResolution(BaseModel):
    """Cách thức và nơi xử lý khi phát sinh tranh chấp giữa các bên."""

    method: str = ""
    venue: str = ""


class ContractGraphExtraction(BaseModel):
    """Toàn bộ tri thức pháp lý (các bên, luật áp dụng, quan hệ giữa các Điều) rút ra từ 1 hợp đồng."""

    parties: List[Party] = Field(default_factory=list)
    governing_law: GoverningLaw = Field(default_factory=GoverningLaw)
    dispute_resolution: DisputeResolution = Field(default_factory=DisputeResolution)
    clauses: List[ClauseRelations] = Field(default_factory=list)
