"""Danh sách loại điều khoản (ClauseType) cố định dùng khi trích xuất tri thức hợp đồng."""

from __future__ import annotations

from typing import Literal

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
