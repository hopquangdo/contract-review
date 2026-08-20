"""Chuẩn hoá định dạng Markdown của hợp đồng trước khi đưa vào các bước xử lý tiếp theo."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_LABEL_MAX_LEN = 40
_SNIPPET_MAX_CHARS = 60

# Ghi chú review Word (track-changes comment bubble, vd "Commented [PTNH1]: VTIT update") mà
# Docling chèn thẳng vào dòng văn bản tại đúng vị trí neo comment - không phải nội dung hợp đồng
# thật, chỉ là rác review nội bộ trước khi ký. Phải lọc bỏ TRƯỚC mọi bước tách Điều/Khoản/Excerpt
# (kể cả bước LLM tách Excerpt - xem helpers/excerpt_splitting.py) vì nếu không: (1) rác này lẫn vào
# Clause/Excerpt lưu trong graph, gây nhiễu khi LLM trích xuất quan hệ hoặc khi retrieval trả về
# làm evidence; (2) LLM tách Excerpt tự động bỏ qua đoạn rác này khi tách theo Ý (đúng ý), nhưng
# validate "khớp nguyên văn 100%" sẽ coi đó là mất nội dung và fallback oan. Chỉ xoá marker + phần
# text CÙNG DÒNG với nó (không cố xoá cả đoạn văn theo sau, vì ranh giới đoạn comment không luôn rõ
# ràng - vd đôi khi nội dung comment lại nằm ở dòng/đoạn kế tiếp do Docling tách anchor giữa câu).
_REVIEW_COMMENT_PATTERN = re.compile(r"Commented \[[^\]]*\]:[^\n]*")


def normalize_markdown(text: str) -> str:
    """Chuẩn hoá Markdown: bỏ ghi chú review Word lẫn vào văn bản, gộp cặp "Nhãn"/"Giá trị" bị
    Docling tách ra 2 dòng, dọn dòng trống thừa, và bỏ số thứ tự danh sách rác Docling tự sinh đè
    trước số hiệu Khoản.

    Args:
        text: Nội dung Markdown thô (thường là output của docling_parser).

    Returns:
        Nội dung Markdown đã chuẩn hoá.
    """
    n_comments = len(_REVIEW_COMMENT_PATTERN.findall(text))
    if n_comments:
        text = _REVIEW_COMMENT_PATTERN.sub("", text)
        logger.info("Chuẩn hoá markdown: đã bỏ %d ghi chú review Word ('Commented [...]')", n_comments)

    lines = text.split("\n")
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        is_label_like = (
            stripped
            and not stripped.startswith("#")
            and len(stripped) < _LABEL_MAX_LEN
        )
        if is_label_like and i + 1 < len(lines) and lines[i + 1].strip() == "":
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("#"):
                value_stripped = lines[j].strip()
                # 2 dạng gộp được: "Nhãn:" + dòng trống + "Giá trị", hoặc "Nhãn" (không dấu
                # hai chấm) + dòng trống + ": Giá trị" (dấu hai chấm nằm ở đầu dòng giá trị).
                if stripped.endswith(":"):
                    merged.append(f"{stripped} {value_stripped.lstrip(':').strip()}")
                    i = j + 1
                    continue
                if value_stripped.startswith(":"):
                    merged.append(f"{stripped}: {value_stripped.lstrip(':').strip()}")
                    i = j + 1
                    continue
        merged.append(line)
        i += 1

    result = "\n".join(merged)
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Docling đôi khi tự đánh số thứ tự danh sách ("2.", "9.", "7."...) đè ngay trước 1 số hiệu
    # Khoản thật (vd "2. 2.2. Nghĩa vụ của Khách hàng:", hay "4. 3.3.2. Nghiệm thu...") - số thứ
    # tự đó là rác do parser tự sinh, không có trong văn bản gốc, phải bỏ để không cản trở nhận
    # diện ranh giới Khoản (xem ingestion/excerpt_splitter.SUB_CLAUSE_PATTERN, dùng chung cho
    # section_splitter.py). Lookahead dùng ĐÚNG pattern số hiệu Khoản hợp lệ "\d+(?:\.\d+)+"
    # (không hard-code "đúng 2 cấp") để khớp MỌI độ sâu (2, 3, 4 cấp...) - tránh phải vá thêm
    # từng trường hợp cụ thể mỗi khi gặp 1 độ sâu mới trong hợp đồng khác.
    _GARBAGE_LIST_NUMBER_PATTERN = r"(?m)^(\s*)\d+\.\s+(?=\d+(?:\.\d+)+\.?\s)"
    n_before = len(re.findall(_GARBAGE_LIST_NUMBER_PATTERN, result))
    result = re.sub(_GARBAGE_LIST_NUMBER_PATTERN, r"\1", result)
    if n_before:
        logger.info("Chuẩn hoá markdown: đã bỏ %d số thứ tự danh sách rác đè trước số Khoản", n_before)

    logger.debug("Chuẩn hoá markdown: %d dòng vào -> %d dòng sau gộp", len(lines), len(merged))
    return result


def snippet(text: str) -> str:
    """Rút gọn 1 đoạn text thành 1 đoạn ngắn để làm nhãn hiển thị khi không có tiêu đề riêng - gộp
    khoảng trắng/xuống dòng thừa rồi cắt ở _SNIPPET_MAX_CHARS ký tự, không cắt giữa từ."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_MAX_CHARS].rsplit(" ", 1)[0] + "…"
