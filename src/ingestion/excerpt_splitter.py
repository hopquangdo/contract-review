"""Tách nội dung 1 Điều khoản dài thành nhiều Excerpt (đơn vị embedding/retrieval) theo mục con."""

from __future__ import annotations

import re

# Điều dưới ngưỡng này giữ nguyên 1 Excerpt duy nhất (đúng hành vi cũ) - chỉ tách khi 1 embedding
# đại diện cho cả khối văn bản sẽ mất độ chính xác (Điều dài nhiều Khoản khác chủ đề nhau).
_MAX_EXCERPT_CHARS = 800

# Ranh giới mục con kiểu "17.1", "17.1.", "17.1.2" ở đầu dòng - có thể có "-"/"•" phía trước do
# Docling render bullet, HOẶC "#"/"##" phía trước do Docling render nhầm mốc Khoản thành heading
# Markdown (gặp thực tế: "## 4.2. Nghĩa vụ của VTIT:"). Định nghĩa DÙNG CHUNG cho cả
# excerpt_splitter (tách Excerpt để embedding) lẫn section_splitter (tách Clause = Khoản pháp
# lý) - 1 nơi định nghĩa duy nhất, tránh lệch pattern giữa 2 module.
SUB_CLAUSE_PATTERN = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?(?:[-•]\s*)?(\d+(?:\.\d+)+)\.?\s")

# Ranh giới mục con kiểu chữ cái "a)", "b)"... - dùng khi 1 Khoản không có mốc "x.y" nào (vd
# Khoản định nghĩa liệt kê a) 'Hợp đồng'..., b) 'Dịch vụ'...) - fallback TRƯỚC khi phải cắt cứng
# theo ký tự, vì cắt cứng dễ xé đôi từ ghép tiếng Việt giữa chừng (vd "Hợp" | "đồng này").
_LETTER_ITEM_PATTERN = re.compile(r"(?m)^\s*(?:[-•]\s*)?([a-zA-Z])\)\s")

_SPLIT_PATTERNS = [SUB_CLAUSE_PATTERN, _LETTER_ITEM_PATTERN]


def split_clause_into_excerpts(text: str, max_chars: int = _MAX_EXCERPT_CHARS) -> list[str]:
    """Trả về danh sách đoạn văn bản (Excerpt) - LUÔN tách theo mục con (mốc "x.y" rồi tới "a)")
    nếu tìm được ranh giới, mỗi mục con luôn là 1 Excerpt riêng (không gộp lại dù ngắn) để tối đa
    độ chính xác truy hồi (1 embedding chỉ đại diện đúng 1 ý). Chỉ giữ nguyên [text] khi không có
    ranh giới mục con nào (< 2 match) và đủ ngắn, hoặc cắt cứng theo ký tự khi không có ranh giới
    và quá dài.

    KHÔNG chèn câu dẫn trước mục con đầu tiên (vd "VTIT vẫn có quyền:") vào từng Excerpt - từng
    thử (xem git history) nhưng gây dilution: các mục a/b/c/d của cùng 1 Khoản dùng chung 1 đoạn
    câu dẫn giống hệt nhau trong embedding, làm giảm độ phân biệt giữa chúng - đúng lúc similarity
    của model đang dùng vốn đã bị nén chặt (xem MIN_RETRIEVAL_SCORE trong config/settings.py)."""
    segments = _split_by_first_matching_pattern(text)
    if segments is None:
        return [text] if len(text) <= max_chars else _split_by_char_budget(text, max_chars)

    final: list[str] = []
    for seg in segments:
        final.extend(_split_by_char_budget(seg, max_chars) if len(seg) > max_chars else [seg])
    return final


def _split_by_first_matching_pattern(text: str) -> list[str] | None:
    """Thử lần lượt SUB_CLAUSE_PATTERN (mốc "x.y") rồi _LETTER_ITEM_PATTERN (mốc "a)", "b)"...)
    - dùng pattern ĐẦU TIÊN khớp >= 2 lần, trả None nếu không pattern nào đủ ranh giới. Câu dẫn
    trước mục con đầu tiên (nếu có, vd "VTIT vẫn có quyền:") đứng thành 1 Excerpt riêng - CHẤP
    NHẬN excerpt này đôi khi cụt/ít ngữ nghĩa hơn, đổi lại các mục a/b/c/d không bị dilution do
    lặp lại cùng 1 câu dẫn trong embedding của tất cả các mục."""
    for pattern in _SPLIT_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) < 2:
            continue
        segments = []
        head = text[: matches[0].start()].strip()
        if head:
            segments.append(head)
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            # m.start(1): bỏ "#"/"##"/"-"/"•" đứng trước số/chữ cái - chỉ là ký hiệu trình bày,
            # không phải nội dung, đưa vào Excerpt sẽ render sai khi qua Markdown.
            segments.append(text[m.start(1) : end].strip())
        return segments
    return None


# Ranh giới ưu tiên khi phải cắt cứng, từ "tốt" nhất tới "chấp nhận được" nhất: xuống dòng (hết
# đoạn) > hết câu (". ") > hết mệnh đề (";"/",") > khoảng trắng. KHÔNG dừng ở khoảng trắng trước
# các mức trên vì tiếng Việt nhiều từ ghép 2+ âm tiết cách nhau bằng dấu cách (vd "quy định",
# "Hợp đồng") - cắt đúng ngay giữa dấu cách đó vẫn xé đôi 1 từ dù về mặt ký tự là hợp lệ.
_BREAK_MARKERS = ["\n", ". ", "; ", ", ", " "]


def _split_by_char_budget(text: str, max_chars: int) -> list[str]:
    """Cắt cứng theo ngân sách ký tự - phương án CUỐI khi không còn ranh giới ngữ nghĩa nào nhỏ
    hơn để dựa vào (mục con, mục chữ cái). Lùi điểm cắt về ranh giới câu/mệnh đề gần nhất trước
    max_chars, chỉ lùi về khoảng trắng đơn thuần nếu không tìm được ranh giới nào tốt hơn."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            for marker in _BREAK_MARKERS:
                boundary = text.rfind(marker, start, end)
                if boundary > start:
                    # Cắt NGAY SAU dấu câu (giữ nó lại với câu trước), trước khoảng trắng theo
                    # sau - vd marker ". " (2 ký tự) thì cắt tại boundary+1 (ngay sau dấu ".").
                    end = boundary + len(marker) - 1
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks
