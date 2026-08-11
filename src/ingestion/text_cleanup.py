"""Chuẩn hoá định dạng Markdown của hợp đồng trước khi đưa vào các bước xử lý tiếp theo."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_LABEL_MAX_LEN = 40


def normalize_markdown(text: str) -> str:
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
    # Khoản thật (vd "2. 2.2. Nghĩa vụ của Khách hàng:") - số thứ tự đó là rác do parser tự
    # sinh, không có trong văn bản gốc, phải bỏ để không cản trở nhận diện ranh giới Khoản (xem
    # ingestion/excerpt_splitter.SUB_CLAUSE_PATTERN, dùng chung cho section_splitter.py).
    n_before = len(re.findall(r"(?m)^\s*\d+\.\s+(?=\d+\.\d+\.?\s)", result))
    result = re.sub(r"(?m)^(\s*)\d+\.\s+(?=\d+\.\d+\.?\s)", r"\1", result)
    if n_before:
        logger.info("Chuẩn hoá markdown: đã bỏ %d số thứ tự danh sách rác đè trước số Khoản", n_before)

    logger.debug("Chuẩn hoá markdown: %d dòng vào -> %d dòng sau gộp", len(lines), len(merged))
    return result
