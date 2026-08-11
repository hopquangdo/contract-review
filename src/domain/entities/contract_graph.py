"""Schema Pydantic cho tri thức trích xuất từ hợp đồng, tương ứng cấu trúc graph sau:

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
   │                                             ├── DEFINES ──────► Definition
   │                                             └── USES_TERM ────► Definition
   |
   ├── GOVERNED_BY ─────► GoverningLaw
   |
   └── HAS_DISPUTE_RULE ► DisputeResolution
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from domain.clause_taxonomy import ClauseTypeLabel


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


class Definition(BaseModel):
    """Một thuật ngữ hợp đồng cùng nghĩa được quy định chính thức cho nó."""

    term: str
    definition: str


class ClauseRelations(BaseModel):
    """Phân loại và các mối liên hệ với những Điều khác mà LLM suy luận ra cho 1 Điều khoản."""

    clause_number: str
    clause_type: ClauseTypeLabel = Field(description="Loại điều khoản - chọn đúng 1 giá trị trong danh sách cho phép.")
    refers_to: List[str] = Field(default_factory=list, description="Số hiệu các Điều được tham chiếu trực tiếp.")
    depends_on: List[str] = Field(default_factory=list, description="Số hiệu các Điều mà Điều này phụ thuộc.")
    exception_to: List[str] = Field(default_factory=list, description="Số hiệu các Điều mà Điều này là ngoại lệ của.")
    definitions: List[Definition] = Field(default_factory=list, description="Thuật ngữ được định nghĩa trong Điều này.")
    uses_terms: List[str] = Field(
        default_factory=list,
        description="Các thuật ngữ đã định nghĩa Ở NƠI KHÁC (không phải definitions của chính Điều này) mà Điều này SỬ DỤNG/nhắc tới.",
    )


class ContractGraphExtraction(BaseModel):
    """Toàn bộ tri thức pháp lý (các bên, luật áp dụng, quan hệ giữa các Điều) rút ra từ 1 hợp đồng."""

    parties: List[Party] = Field(default_factory=list)
    governing_law: GoverningLaw = Field(default_factory=GoverningLaw)
    dispute_resolution: DisputeResolution = Field(default_factory=DisputeResolution)
    clauses: List[ClauseRelations] = Field(default_factory=list)


class Section(BaseModel):
    """Một nhóm các Điều khoản có liên quan trong cấu trúc phân cấp của hợp đồng."""

    number: str
    title: str
    clause_numbers: List[str] = Field(default_factory=list)


class Clause(BaseModel):
    """Nội dung nguyên văn của 1 Điều khoản cụ thể trong hợp đồng."""

    number: str
    title: str
    text: str
