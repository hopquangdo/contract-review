"""Schema Pydantic cấp Điều khoản (Clause/Section) - tách khỏi schema/contract.py (cấp Hợp đồng)."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

CLAUSE_TYPES: tuple[str, ...] = (
    "Đối tượng hợp đồng",
    "Giá và thanh toán",
    "Quyền và nghĩa vụ",
    "Bảo hành",
    "Bảo mật",
    "Sở hữu trí tuệ",
    "Bất khả kháng",
    "Chấm dứt hợp đồng",
    "Giải quyết tranh chấp",
    "Phạt vi phạm",
    "Bồi thường thiệt hại",
    "Định nghĩa",
    "Thông tin chung và các bên tham gia hợp đồng",
    "Khác",
)

ClauseTypeLabel = Literal[
    "Đối tượng hợp đồng",
    "Giá và thanh toán",
    "Quyền và nghĩa vụ",
    "Bảo hành",
    "Bảo mật",
    "Sở hữu trí tuệ",
    "Bất khả kháng",
    "Chấm dứt hợp đồng",
    "Giải quyết tranh chấp",
    "Phạt vi phạm",
    "Bồi thường thiệt hại",
    "Định nghĩa",
    "Thông tin chung và các bên tham gia hợp đồng",
    "Khác",
]


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
    appendix_refs: List[str] = Field(
        default_factory=list,
        description="Số hiệu Clause Phụ lục được tham chiếu (tách riêng khỏi refers_to vì Phụ lục "
        "cần chiến lược mở rộng retrieval khác - xem knowledge_graph/graph.py::Graph.expand_by_appendix_refs).",
    )
    definitions: List[Definition] = Field(default_factory=list, description="Thuật ngữ được định nghĩa trong Điều này.")
    uses_terms: List[str] = Field(
        default_factory=list,
        description="Các thuật ngữ đã định nghĩa Ở NƠI KHÁC (không phải definitions của chính Điều này) mà Điều này SỬ DỤNG/nhắc tới.",
    )


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
