"""Tách nội dung hợp đồng (markdown) thành Section và Clause (đơn vị pháp lý = Khoản 'x.y',
fallback về cả Điều nếu Điều không có Khoản con nào)."""

from __future__ import annotations

import logging
import re

from ingestion.excerpt_splitter import SUB_CLAUSE_PATTERN

logger = logging.getLogger(__name__)

_MIN_MATCHES_TO_ACCEPT = 2

SECTION_PATTERNS = [
    re.compile(r"(?m)^##\s*PHẦN\s+([IVX]+)\.\s*(.*)$"),
    re.compile(r"(?m)^##\s*CHƯƠNG\s+([IVX\d]+)\.\s*(.*)$"),
    re.compile(r"(?m)^##\s*PART\s+([IVX\d]+)\.\s*(.*)$"),
]
CLAUSE_PATTERNS = [
    re.compile(r"(?m)^##\s*ĐIỀU\s+(\d+)\.\s*(.*)$"),
    re.compile(r"(?m)^##\s*MỤC\s+(\d+)\.\s*(.*)$"),
    re.compile(r"(?m)^##\s*ARTICLE\s+(\d+)\.\s*(.*)$"),
]

def _first_matching_pattern(text: str, patterns: list[re.Pattern]) -> list[re.Match]:
    """Trả về danh sách match của pattern ĐẦU TIÊN khớp >= _MIN_MATCHES_TO_ACCEPT lần."""
    for pattern in patterns:
        matches = list(pattern.finditer(text))
        if len(matches) >= _MIN_MATCHES_TO_ACCEPT:
            return matches
    return []


def _make_clause(
    number: str, title: str, article_number: str, article_title: str, text: str, pos: int, is_preamble: bool = False
) -> dict:
    """Cấu trúc 1 Clause dùng CHUNG cho mọi nơi dựng Clause trong module này (preamble, fallback
    nguyên Điều, hay từng Khoản tách ra) - tránh lặp lại cùng 1 bộ field ở nhiều nơi."""
    return {
        "number": number,
        "title": title,
        "article_number": article_number,
        "article_title": article_title,
        "text": text,
        "pos": pos,
        "is_preamble": is_preamble,
    }


def _split_article_into_clauses(number: str, title: str, body: str, abs_offset: int, seen_numbers: set) -> list[dict]:
    """1 Điều -> nhiều Clause (Khoản 'x.y') nếu có >= _MIN_MATCHES_TO_ACCEPT mốc Khoản, ngược
    lại fallback về đúng hành vi cũ: cả Điều là 1 Clause duy nhất (number='x').

    seen_numbers: số hiệu Clause đã sinh ra từ các Điều TRƯỚC đó trong cùng hợp đồng - văn bản
    gốc đôi khi đánh số Khoản sai (lặp lại số của Điều khác, vd Điều 3 lại dùng nhãn "2.1"-"2.3"
    trùng Điều 2) - nếu tách theo đúng nhãn trong văn bản sẽ tạo 2 Clause khác nhau NHƯNG CÙNG
    number, khiến builder.py MERGE nhầm thành 1 node (mất dữ liệu âm thầm). Phát hiện trùng thì
    bỏ qua tách Khoản cho CHÍNH Điều đang lỗi, giữ cả Điều làm 1 Clause (an toàn, không mất dữ
    liệu, chỉ kém chi tiết hơn cho đúng Điều bị lỗi đánh số)."""
    sub_matches = list(SUB_CLAUSE_PATTERN.finditer(body))
    collisions = [m.group(1) for m in sub_matches if m.group(1) in seen_numbers]
    if len(sub_matches) < _MIN_MATCHES_TO_ACCEPT or collisions:
        if collisions:
            logger.warning(
                "Điều %s: số hiệu Khoản %s trùng với Khoản đã có ở Điều khác (lỗi đánh số trong "
                "văn bản gốc) - giữ nguyên cả Điều làm 1 Clause thay vì tách, để không ghi đè "
                "dữ liệu.",
                number, collisions,
            )
        seen_numbers.add(number)
        return [_make_clause(number, title, number, title, f"Điều {number}. {title}\n\n{body}".strip(), abs_offset)]

    clauses = []
    head = body[: sub_matches[0].start()].strip()
    for i, m in enumerate(sub_matches):
        sub_number = m.group(1)
        end = sub_matches[i + 1].start() if i + 1 < len(sub_matches) else len(body)
        # m.start(1) (không phải m.start()) - bỏ mọi "#"/"##"/"-"/"•" đứng trước số hiệu, vì đó
        # chỉ là ký hiệu Docling dùng để trình bày, đưa vào text sẽ bị marked.js render nhầm
        # thành heading/bullet lồng bất thường trong Evidence.
        text = body[m.start(1) : end].strip()
        if i == 0 and head:
            text = f"{head}\n\n{text}"
        # Khoản không có tiêu đề riêng trong văn bản - để title="" ĐÚNG sự thật (không mượn
        # tiêu đề Điều cha gán vào, vì làm vậy khiến node Clause hiện caption sai/gây hiểu lầm
        # khi soi trực tiếp trong Neo4j Browser - vd Khoản 1.2 là "Định nghĩa" nhưng hiện thành
        # "ĐỐI TƯỢNG HỢP ĐỒNG" vì mượn title Điều 1). Hiển thị "đầy đủ ngữ cảnh" là việc của
        # tầng trình bày (frontend gộp theo Điều), không phải giả dữ liệu gốc trong graph.
        clauses.append(_make_clause(sub_number, "", number, title, text, abs_offset + m.start()))
        seen_numbers.add(sub_number)
    return clauses


def split_into_sections_and_clauses(markdown_text: str) -> tuple[list[dict], list[dict]]:
    section_matches = _first_matching_pattern(markdown_text, SECTION_PATTERNS)
    article_matches = _first_matching_pattern(markdown_text, CLAUSE_PATTERNS)

    clauses = []

    # Phần mở đầu (quốc hiệu, thông tin các bên, người đại diện/chức vụ, "Xét rằng...") nằm
    # TRƯỚC "ĐIỀU 1" và ngoài mọi Section - nếu bỏ qua, các câu hỏi checklist về "người đại
    # diện ký kết", "chức vụ", "ủy quyền" sẽ không bao giờ retrieve được bằng chứng vì không
    # có Clause nào chứa nội dung này. Coi nó là 1 Clause với is_preamble=True (số hiệu "0" chỉ
    # để có 1 khoá duy nhất trong graph, KHÔNG phải số Điều thật) để vẫn được embedding + truy hồi.
    preamble_end = article_matches[0].start() if article_matches else len(markdown_text)
    preamble_text = markdown_text[:preamble_end].strip()
    if preamble_text:
        preamble_title = "Thông tin chung và các bên tham gia hợp đồng"
        clauses.append(_make_clause("0", preamble_title, "0", preamble_title, preamble_text, -1, is_preamble=True))

    seen_numbers = {c["number"] for c in clauses}  # gồm "0" (preamble) nếu có
    for i, m in enumerate(article_matches):
        number = m.group(1)
        title = m.group(2).strip()
        start = m.end()
        end = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(markdown_text)
        body = markdown_text[start:end]
        clauses.extend(_split_article_into_clauses(number, title, body, start, seen_numbers))

    sections = []
    for i, m in enumerate(section_matches):
        number = m.group(1)
        title = m.group(2).strip()
        start = m.start()
        end = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(markdown_text)
        clause_numbers = [c["number"] for c in clauses if start <= c["pos"] < end]
        sections.append({"number": number, "title": title, "clause_numbers": clause_numbers})

    if not sections:
        sections = [{"number": "1", "title": "Toàn bộ hợp đồng", "clause_numbers": [c["number"] for c in clauses]}]
    elif preamble_text:
        # Gắn Clause "0" vào Section đầu tiên để không bị rơi ra ngoài (mọi Clause phải thuộc
        # 1 Section vì knowledge_graph.builder.CREATE_CLAUSES match theo section_number).
        sections[0]["clause_numbers"].insert(0, "0")

    logger.info("Tách hợp đồng thành %d section, %d clause", len(sections), len(clauses))
    if not clauses:
        logger.warning("Không tách được clause nào từ tài liệu")

    return sections, clauses
