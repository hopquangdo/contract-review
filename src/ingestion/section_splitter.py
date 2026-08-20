"""Tách nội dung hợp đồng (markdown) thành Section và Clause.

Clause là đơn vị pháp lý = Khoản "x.y", fallback về cả Điều nếu Điều không có Khoản con nào.
"""

from __future__ import annotations

import logging
import re

from ingestion.excerpt_splitter import SUB_CLAUSE_PATTERN
from ingestion.clause_repair import repair_clause_span

logger = logging.getLogger(__name__)

_MIN_MATCHES_TO_ACCEPT = 2

SECTION_PATTERNS = [
    re.compile(r"(?m)^##\s*PHẦN\s+([IVX]+)[.:]\s*(.*)$"),
    re.compile(r"(?m)^##\s*CHƯƠNG\s+([IVX\d]+)[.:]\s*(.*)$"),
    re.compile(r"(?m)^##\s*PART\s+([IVX\d]+)[.:]\s*(.*)$"),
]
# Dấu phân cách sau số hiệu Điều/Khoản có thể là "." hoặc ":" tuỳ hợp đồng (vd "ĐIỀU 1: ..." hay
# "ĐIỀU 1. ...") - chấp nhận cả 2 để không bỏ sót toàn bộ Điều chỉ vì khác dấu câu.
CLAUSE_PATTERNS = [
    re.compile(r"(?m)^##\s*ĐIỀU\s+(\d+)[.:]\s*(.*)$"),
    re.compile(r"(?m)^##\s*MỤC\s+(\d+)[.:]\s*(.*)$"),
    re.compile(r"(?m)^##\s*ARTICLE\s+(\d+)[.:]\s*(.*)$"),
]
# Phụ lục không đánh số Khoản con như Điều - chỉ cần khớp ĐÚNG 1 lần cũng coi là hợp lệ (khác
# SECTION/CLAUSE_PATTERNS cần >= _MIN_MATCHES_TO_ACCEPT để tránh khớp nhầm câu văn thường), vì
# hợp đồng có khi chỉ có duy nhất 1 Phụ lục.
# [ \t]* (không phải \s*) trước phần tiêu đề - \s* khớp cả xuống dòng, khiến heading không có tiêu
# đề trên cùng dòng (rất phổ biến - Phụ lục hay ghi tiêu đề ở dòng heading KẾ TIẾP) bị nuốt nhầm
# dòng trống rồi bắt luôn đoạn văn/heading sau làm "title" của chính Phụ lục (bug từng gặp).
APPENDIX_PATTERN = re.compile(r"(?m)^##[ \t]*PHỤ LỤC[ \t]+([^\s.]+)\.?[ \t]*(.*)$")
# Mục con BÊN TRONG 1 Phụ lục không theo quy tắc đánh số "Điều x"/"Khoản x.y" như thân hợp đồng -
# thường là heading tự do (vd "## A. Tiêu chí kỹ thuật", "## 1. Yêu cầu chung") không có 1 mẫu số
# hiệu cố định để bắt bằng regex riêng - nên nhận diện TỔNG QUÁT mọi heading cấp 2/3, không giới
# hạn từ khóa hay định dạng số hiệu cụ thể nào (khác CLAUSE_PATTERNS chỉ nhận đúng "ĐIỀU"/"MỤC").
_APPENDIX_SUBHEADING_PATTERN = re.compile(r"(?m)^#{2,3}[ \t]+(.+)$")

def _first_matching_pattern(text: str, patterns: list[re.Pattern]) -> list[re.Match]:
    """Trả về danh sách match của pattern ĐẦU TIÊN khớp >= _MIN_MATCHES_TO_ACCEPT lần."""
    for pattern in patterns:
        matches = list(pattern.finditer(text))
        if len(matches) >= _MIN_MATCHES_TO_ACCEPT:
            return matches
    return []


def _make_clause(
    number: str, title: str, article_number: str, article_title: str, text: str, pos: int,
    is_preamble: bool = False, is_appendix: bool = False,
) -> dict:
    """Cấu trúc 1 Clause dùng CHUNG cho mọi nơi dựng Clause trong module này (preamble, fallback
    nguyên Điều, từng Khoản tách ra, hay Phụ lục) - tránh lặp lại cùng 1 bộ field ở nhiều nơi."""
    return {
        "number": number,
        "title": title,
        "article_number": article_number,
        "article_title": article_title,
        "text": text,
        "pos": pos,
        "is_preamble": is_preamble,
        "is_appendix": is_appendix,
    }


def _split_article_into_clauses(number: str, title: str, body: str, abs_offset: int, seen_numbers: set) -> list[dict]:
    """1 Điều -> nhiều Clause (Khoản 'x.y') nếu có >= _MIN_MATCHES_TO_ACCEPT mốc Khoản, ngược
    lại fallback về đúng hành vi cũ: cả Điều là 1 Clause duy nhất (number='x').

    seen_numbers: số hiệu Clause đã sinh ra từ các Điều TRƯỚC đó trong cùng hợp đồng - văn bản
    gốc đôi khi đánh số Khoản sai (lặp lại số của Điều khác, vd Điều 3 lại dùng nhãn "2.1"-"2.3"
    trùng Điều 2, do người soạn copy nguyên Điều 2 rồi quên đổi số). Tách thẳng theo đúng nhãn
    trong văn bản sẽ tạo 2 Clause khác nhau NHƯNG CÙNG number, khiến builder.py MERGE nhầm thành 1
    node (mất dữ liệu âm thầm) - phát hiện trùng thì SUY LUẬN lại số hiệu đúng bằng cách đánh số
    THEO THỨ TỰ XUẤT HIỆN dưới tiền tố "number" thật của Điều (vd "3.1", "3.2", "3.3" thay vì nhãn
    sai "2.1", "2.2", "2.3" chép nhầm trong văn bản gốc) - vẫn tách chi tiết được thay vì gộp cả
    Điều thành 1 Clause, chỉ đánh số lại theo Điều đang đứng, không đổi nội dung/thứ tự thật."""
    sub_matches = list(SUB_CLAUSE_PATTERN.finditer(body))
    collisions = [m.group(1) for m in sub_matches if m.group(1) in seen_numbers]
    if collisions:
        logger.warning(
            "Điều %s: số hiệu Khoản %s trong văn bản gốc trùng với Khoản đã có ở Điều khác (lỗi "
            "đánh số/copy nhầm) - suy luận đánh số lại theo thứ tự dưới Điều %s thay vì nhãn gốc.",
            number, collisions, number,
        )

    if len(sub_matches) < _MIN_MATCHES_TO_ACCEPT:
        seen_numbers.add(number)
        # KHÔNG tự chèn "Điều {number}. {title}" vào text - "title" đã là field riêng, và tầng
        # trình bày (rag/builder.py::ContextBuilder.group_by_article) LUÔN tự thêm header này khi
        # gộp Clause theo Điều, nên chèn sẵn ở đây sẽ lặp header 2 lần (từng là bug thật quan sát
        # được: "Điều 14. BẢO MẬT THÔNG TIN" xuất hiện liên tiếp 2 dòng trong context LLM).
        return [_make_clause(number, title, number, title, body.strip(), abs_offset)]

    clauses = []
    head = body[: sub_matches[0].start()].strip()
    for i, m in enumerate(sub_matches):
        # Nhãn gốc trong văn bản, TRỪ KHI nó trùng với 1 Khoản đã có (Điều khác) - khi đó suy luận
        # lại bằng "number.thứ_tự" (thứ tự xuất hiện trong CHÍNH Điều này), tránh đụng độ mà vẫn
        # giữ được độ chi tiết tách Khoản thay vì gộp nguyên Điều làm 1 Clause.
        sub_number = m.group(1)
        if sub_number in seen_numbers or sub_number in collisions:
            sub_number = f"{number}.{i + 1}"
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


def _split_appendix_into_clauses(label: str, title: str, body: str, abs_offset: int) -> list[dict]:
    """1 Phụ lục -> 1 Clause GỐC (number="PL<label>") + N Clause con (number="PL<label>.i") theo
    từng heading cấp 2/3 tìm thấy bên trong (xem _APPENDIX_SUBHEADING_PATTERN) - tương tự
    _split_article_into_clauses() nhưng KHÔNG dùng SUB_CLAUSE_PATTERN (đó là cho Khoản "x.y" của
    Điều, Phụ lục không theo quy tắc đánh số đó).

    Clause GỐC LUÔN tồn tại (quy tắc đã chốt: mọi tham chiếu CHUNG CHUNG "xem Phụ lục X" phải có 1
    đích hợp lệ để trỏ vào, bất kể Phụ lục có đoạn mở đầu tự nhiên hay không): nếu có đoạn văn
    trước mục con đầu tiên thì dùng làm nội dung gốc; nếu Phụ lục nhảy thẳng vào mục con đầu tiên
    thì tự dựng nội dung tối thiểu (tiêu đề + liệt kê tiêu đề các mục con) thay vì để trống."""
    number = f"PL{label}"
    sub_matches = list(_APPENDIX_SUBHEADING_PATTERN.finditer(body))

    if not sub_matches:
        # KHÔNG tự chèn "Phụ lục {label}. {title}" vào text - cùng lý do như nhánh Điều 1 Clause ở
        # _split_article_into_clauses (group_by_article đã tự thêm header, chèn sẵn ở đây bị lặp).
        return [_make_clause(number, title, number, title, body.strip(), abs_offset, is_appendix=True)]

    head = body[: sub_matches[0].start()].strip()
    sub_clauses = []
    sub_titles = []
    for i, m in enumerate(sub_matches):
        sub_number = f"{number}.{i + 1}"
        sub_title = m.group(1).strip()
        end = sub_matches[i + 1].start() if i + 1 < len(sub_matches) else len(body)
        text = body[m.start(1) : end].strip()
        sub_clauses.append(_make_clause(sub_number, sub_title, number, title, text, abs_offset + m.start(), is_appendix=True))
        sub_titles.append(sub_title)

    if head:
        # KHÔNG chèn header "Phụ lục {label}. {title}" - cùng lý do các nhánh trên (group_by_article
        # tự thêm khi gộp).
        root_text = head
    else:
        # Không có đoạn văn mở đầu tự nhiên (Phụ lục nhảy thẳng vào mục con đầu tiên) - PHẢI tự dựng
        # nội dung tối thiểu cho Clause GỐC (không được để trống, xem docstring hàm), nên vẫn cần
        # nhắc tên Phụ lục ở đây (không có "head" nào khác để làm nội dung) - trường hợp DUY NHẤT còn
        # giữ header trong text, chấp nhận khả năng lặp nhẹ với group header khi qua group_by_article.
        toc = "\n".join(f"- {t}" for t in sub_titles)
        root_text = f"Phụ lục {label}. {title}\n\nGồm các mục:\n{toc}"
    root_clause = _make_clause(number, title, number, title, root_text, abs_offset, is_appendix=True)

    return [root_clause] + sub_clauses


def _sort_key_for_number(number: str) -> list:
    return [int(p) if p.isdigit() else p for p in number.split(".")]


def _clause_contains_number(clause_text: str, number: str) -> bool:
    """True nếu `number` xuất hiện đứng đầu 1 dòng bên trong clause_text (cùng hình dạng match
    với SUB_CLAUSE_PATTERN, nhưng khoá cứng đúng 1 số hiệu cụ thể thay vì bắt bất kỳ số nào)."""
    pattern = re.compile(rf"(?m)^\s*(?:#{{1,6}}\s*)?(?:[-•]\s*)?{re.escape(number)}\.?\s")
    return pattern.search(clause_text) is not None


def _find_missing_numbers(markdown_text: str, seen_numbers: set[str]) -> list[str]:
    """Số hiệu "x.y" hợp lệ xuất hiện đứng đầu dòng trong markdown_text nhưng KHÔNG có trong
    seen_numbers - dùng chung bởi cả _repair_missing_numbers (lúc build) và
    compute_numbering_diagnostics (benchmark - xem scripts/benchmark_toc_extraction.py)."""
    candidates = {m.group(1) for m in SUB_CLAUSE_PATTERN.finditer(markdown_text)}

    def _is_intentionally_absorbed(n: str) -> bool:
        """True nếu n thuộc 1 Điều bị PHÁT HIỆN TRÙNG SỐ HIỆU nên chủ động giữ nguyên cả Điều
        làm 1 Clause duy nhất (xem _split_article_into_clauses, nhánh "collisions") - không phải
        bỏ sót thật, mà là hành vi AN TOÀN đã chủ đích, nên không cần sửa/cảnh báo lại ở đây."""
        article = n.split(".")[0]
        return article != n and article in seen_numbers

    return sorted((n for n in candidates - seen_numbers if not _is_intentionally_absorbed(n)), key=_sort_key_for_number)


def compute_numbering_diagnostics(markdown_text: str, seen_numbers: set[str]) -> dict:
    """Tính chỉ số recall cho việc tách số hiệu Khoản - dùng cho benchmark/báo cáo chất lượng
    (scripts/benchmark_toc_extraction.py), KHÔNG dùng trong luồng build chính (build dùng
    _repair_missing_numbers, vừa phát hiện vừa thử sửa bằng LLM).

    Args:
        markdown_text: Văn bản gốc (đã qua text_cleanup.normalize_markdown) của 1 hợp đồng.
        seen_numbers: Tập số hiệu Clause ĐÃ CÓ THẬT - lấy từ graph (Neo4j) hoặc từ kết quả
            split_into_sections_and_clauses(), tuỳ nơi gọi.

    Returns:
        dict gồm n_candidates (số hiệu hợp lệ tìm thấy trong văn bản), n_matched, n_missing,
        missing_numbers (danh sách số hiệu bị thiếu) và recall (n_matched / n_candidates, 1.0 nếu
        không có candidate nào).
    """
    candidates = {m.group(1) for m in SUB_CLAUSE_PATTERN.finditer(markdown_text)}
    missing = _find_missing_numbers(markdown_text, seen_numbers)
    n_candidates = len(candidates)
    n_missing = len(missing)
    n_matched = n_candidates - n_missing
    return {
        "n_candidates": n_candidates,
        "n_matched": n_matched,
        "n_missing": n_missing,
        "missing_numbers": missing,
        "recall": (n_matched / n_candidates) if n_candidates else 1.0,
    }


def _repair_missing_numbers(markdown_text: str, clauses: list[dict], seen_numbers: set[str]) -> list[dict]:
    """Quét lại TOÀN VĂN BẢN gốc tìm mọi số hiệu đứng đầu dòng khớp đúng lược đồ "x.y" hợp lệ
    (SUB_CLAUSE_PATTERN), so với tập số hiệu đã thực sự tách thành Clause - đây là lưới an toàn
    TỔNG QUÁT thay cho việc phải liệt kê trước từng dạng rác parser cụ thể (xem
    ingestion/text_cleanup.py): dù nguyên nhân bỏ sót là gì (rác Docling dạng mới chưa từng gặp,
    lỗi đánh số trong văn bản gốc, hay bug khác), miễn số hiệu đó bị nuốt mất sẽ luôn bị phát hiện
    ở đây - việc PHÁT HIỆN luôn là tất định/regex, KHÔNG bao giờ dùng LLM quét toàn văn bản.

    Với mỗi số hiệu bị thiếu, thử gọi LLM sửa CỤC BỘ đúng đoạn Clause cha chứa nó (xem
    ingestion.clause_repair.repair_clause_span) - phạm vi nhỏ nên validate nguyên văn được chặt chẽ.
    Sửa thành công thì THAY THẾ Clause cha bằng các Clause con mới; thất bại (lỗi LLM/validate
    không khớp) thì GIỮ NGUYÊN Clause cha như cũ và chỉ log cảnh báo để người review xác minh thủ
    công - không có nhánh nào tự tin sửa liều.

    Args:
        markdown_text: Toàn văn bản gốc đã qua text_cleanup.normalize_markdown.
        clauses: Danh sách Clause đã tách được (SẼ KHÔNG bị sửa tại chỗ - trả về danh sách mới).
        seen_numbers: Tập số hiệu Clause hiện có - được cập nhật TẠI CHỖ khi có Clause cha bị
            thay thế bằng Clause con mới.

    Returns:
        Danh sách Clause đã áp dụng mọi bản sửa thành công (có thể giống hệt `clauses` nếu không
        có gì cần sửa hoặc mọi lần sửa đều thất bại).
    """
    missing = _find_missing_numbers(markdown_text, seen_numbers)
    if not missing:
        return clauses

    parent_missing: dict[int, list[str]] = {}
    unresolved: list[str] = []
    for n in missing:
        idx = next((i for i, c in enumerate(clauses) if _clause_contains_number(c["text"], n)), None)
        if idx is None:
            unresolved.append(n)
        else:
            parent_missing.setdefault(idx, []).append(n)

    new_clauses = list(clauses)
    for idx in sorted(parent_missing, reverse=True):  # giảm dần để splice không lệch index đã xử lý
        parent = clauses[idx]
        repaired = repair_clause_span(parent["text"], parent_missing[idx])
        if repaired is None:
            unresolved.extend(parent_missing[idx])
            continue
        children = [
            _make_clause(
                sc["number"], "", parent["article_number"], parent["article_title"], sc["text"], parent["pos"],
                is_preamble=parent.get("is_preamble", False), is_appendix=parent.get("is_appendix", False),
            )
            for sc in repaired
        ]
        new_clauses[idx : idx + 1] = children
        seen_numbers.discard(parent["number"])
        seen_numbers.update(sc["number"] for sc in repaired)

    if unresolved:
        logger.warning(
            "Phát hiện %d số hiệu đứng đầu dòng trong văn bản gốc nhưng KHÔNG tách thành Clause nào "
            "(kể cả sau khi thử LLM sửa cục bộ) - khả năng bị rác parser/lỗi đánh số nuốt mất, cần "
            "người review xác minh thủ công: %s",
            len(unresolved), sorted(unresolved, key=_sort_key_for_number),
        )
    return new_clauses


def split_into_sections_and_clauses(markdown_text: str) -> tuple[list[dict], list[dict]]:
    """Tách toàn bộ Markdown hợp đồng thành danh sách Section và danh sách Clause.

    Args:
        markdown_text: Nội dung hợp đồng dạng Markdown (đã qua text_cleanup.normalize_markdown).

    Returns:
        Tuple (sections, clauses): `sections` là danh sách dict {"number", "title",
        "clause_numbers"}; `clauses` là danh sách dict do `_make_clause` tạo ra (gồm cả Clause
        preamble và Clause Phụ lục nếu có).
    """
    section_matches = _first_matching_pattern(markdown_text, SECTION_PATTERNS)
    article_matches = _first_matching_pattern(markdown_text, CLAUSE_PATTERNS)
    appendix_matches = list(APPENDIX_PATTERN.finditer(markdown_text))
    # Phụ lục thường nằm SAU Điều cuối cùng - nếu không chặn riêng, body Điều cuối sẽ chạy tới hết
    # văn bản (xem "end" bên dưới) và nuốt luôn toàn bộ Phụ lục vào làm nội dung của Điều đó. Trần
    # này áp dụng cho MỌI Điều (không chỉ Điều cuối) đề phòng Phụ lục xen giữa các Điều.
    content_end = appendix_matches[0].start() if appendix_matches else len(markdown_text)
    # Phụ lục có thể tự chứa heading "ĐIỀU x"/"MỤC x" của RIÊNG nó (vd Phụ lục về bảo mật có "ĐIỀU
    # 1. ĐỊNH NGHĨA" nội bộ) - những heading này nằm SAU content_end nên KHÔNG phải Điều thật của
    # hợp đồng, phải loại khỏi article_matches (không chỉ cắt ngắn body) để không tạo Clause "ma"
    # (số hiệu trùng lặp/rỗng nội dung) chồng lên đúng nội dung đã nằm trong Clause Phụ lục.
    article_matches = [m for m in article_matches if m.start() < content_end]
    section_matches = [m for m in section_matches if m.start() < content_end]

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
        end = min(end, content_end)
        body = markdown_text[start:end]
        clauses.extend(_split_article_into_clauses(number, title, body, start, seen_numbers))

    # Mỗi "PHỤ LỤC <nhãn>" -> 1 Clause GỐC + N Clause con theo mục con nội bộ (nếu có) - xem
    # _split_appendix_into_clauses(). number="PL<nhãn>" giữ nguyên nhãn gốc trong văn bản để LLM
    # trích xuất quan hệ dễ đối chiếu đúng cách hợp đồng gọi tên (vd "Phụ lục 02" -> "PL02").
    for i, m in enumerate(appendix_matches):
        label = m.group(1).strip()
        title = m.group(2).strip()
        start = m.end()
        end = appendix_matches[i + 1].start() if i + 1 < len(appendix_matches) else len(markdown_text)
        body = markdown_text[start:end]
        appendix_clauses = _split_appendix_into_clauses(label, title, body, start)
        clauses.extend(appendix_clauses)
        seen_numbers.update(c["number"] for c in appendix_clauses)

    clauses = _repair_missing_numbers(markdown_text, clauses, seen_numbers)

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
        # 1 Section vì Graph.build_graph()/CREATE_CLAUSES match theo section_number).
        sections[0]["clause_numbers"].insert(0, "0")

    logger.info("Tách hợp đồng thành %d section, %d clause", len(sections), len(clauses))
    if not clauses:
        logger.warning("Không tách được clause nào từ tài liệu")

    return sections, clauses
