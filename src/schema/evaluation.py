"""Schema Pydantic cho kết quả đánh giá 1 mục checklist - xem checklist/evaluator.py::ChecklistEvaluator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VerificationUnit(BaseModel):
    """1 đơn vị cần xác minh riêng biệt (1 điều kiện/fact/chủ thể) trong pass_criteria/
    violation_criteria/note - xem Bước 1 của system prompt.

    Sinh TRƯỚC 'status' trong ClauseEvaluation để ép model xác minh xong xuôi từng đơn vị
    rồi mới được chốt kết luận, thay vì chốt kết luận trước rồi viết lý do biện minh ngược
    lại (rationalize).
    """

    requirement: str = Field(description="1 đơn vị cần xác minh - 1 điều kiện/fact/chủ thể riêng biệt.")
    result: Literal["met", "not_met", "not_applicable"] = Field(
        description="'met' nếu có bằng chứng trực tiếp đáp ứng; 'not_applicable' nếu điều kiện kích "
        "hoạt yêu cầu này được xác nhận KHÔNG xảy ra/không tồn tại (nên yêu cầu không áp dụng); "
        "'not_met' cho mọi trường hợp còn lại (thiếu bằng chứng, mập mờ, hoặc điều kiện kích hoạt có "
        "xảy ra nhưng không đáp ứng yêu cầu đi kèm)."
    )
    basis: str = Field(description="Bằng chứng trực tiếp (trích dẫn/số Điều) hoặc lý do not_applicable/not_met.")


class ClauseEvaluation(BaseModel):
    """Kết luận đạt/không đạt cho 1 mục checklist, kèm căn cứ, lý do và đề xuất chỉnh sửa."""

    item_id: str = ""
    evidence_clause_numbers: list[str] = Field(
        description="CHỈ số hiệu Điều/Khoản dùng làm căn cứ trực tiếp cho kết luận (vd ['11.1', '11.2']) - "
        "KHÔNG viết lại/trích dẫn nội dung (hệ thống tự lấy nguyên văn từ số hiệu này để hiển thị, "
        "tiết kiệm token output)."
    )
    verification_units: list[VerificationUnit] = Field(
        description="Xác minh TỪNG đơn vị đã xác định ở Bước 1 - 1 phần tử cho MỖI đơn vị, không gộp/bỏ sót."
    )
    violates_prohibition: bool = Field(
        description="True nếu rơi vào bất kỳ violation_criteria nào - không suy ra được từ verification_units "
        "(vốn chỉ theo dõi pass_criteria), phải tự đánh giá riêng."
    )
    reason: str = Field(description="Tóm tắt ngắn gọn mạch lý luận dẫn tới kết luận, dựa trên verification_units.")
    status: str = Field(description="'pass' hoặc 'fail' - sẽ được tính lại bằng code từ verification_units/violates_prohibition, không dùng trực tiếp giá trị này.")
    proposal: list[str] = Field(
        description="Danh sách đề xuất chỉnh sửa nếu fail - MỖI PHẦN TỬ là 1 Ý CHỈNH SỬA RIÊNG BIỆT, "
        "ĐỘC LẬP, TỰ ĐỦ NGHĨA (không viết chung nhiều ý vào 1 phần tử, không đánh số thủ công '1)'/'(1)' "
        "trong text - hệ thống tự hiển thị mỗi phần tử 1 dòng). Nếu pass, trả về list 1 phần tử là xác "
        "nhận ngắn gọn. Với MỖI ý chỉnh sửa (khi fail), phân biệt 3 trường hợp: (1) lỗi nằm ở 1 Điều/"
        "Khoản cụ thể trong hợp đồng - PHẢI nêu rõ số hiệu Điều/Khoản đó và nội dung cụ thể cần sửa; "
        "(2) hợp đồng CHƯA có điều khoản nào phù hợp nhưng chủ đề đáng đưa vào hợp đồng - đề xuất thêm "
        "1 Khoản mới, nêu rõ nên thêm vào Điều liên quan gần nhất; (3) mục checklist yêu cầu tài liệu/"
        "bằng chứng NGOÀI hợp đồng (giấy phép, giấy ủy quyền, chứng nhận...) chứ không phải nội dung "
        "điều khoản - nêu rõ cần bổ sung/xuất trình tài liệu gì, KHÔNG bịa ra 1 số hiệu Điều để trỏ "
        "vào. Luôn tránh nói chung chung kiểu 'cần bổ sung điều khoản về...'."
    )
    confidence: int = Field(ge=0, le=100, description="Điểm tin cậy của kết luận, 0-100.")
