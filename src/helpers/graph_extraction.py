"""Hàm phụ THUẦN (không gọi Neo4j) hỗ trợ Graph.extract_relations/export_contract_graph -
lọc kết quả LLM trích xuất quan hệ (loại tham chiếu/thuật ngữ ảo giác, chuẩn hoá số hiệu Phụ lục
lạc chỗ), sinh nhãn hiển thị cho Clause. Tách khỏi knowledge_graph/graph.py để class Graph
chỉ còn các method thật sự giao tiếp với Neo4j."""

from __future__ import annotations

import logging

from schema.contract import ContractGraphExtraction

logger = logging.getLogger(__name__)


def drop_invalid_references(extraction: ContractGraphExtraction, valid_numbers: set[str]) -> None:
    """Loại bỏ tại chỗ các tham chiếu (refers_to/depends_on/exception_to) trỏ tới số Điều
    không tồn tại trong hợp đồng.

    LLM đôi khi "ảo giác" tham chiếu tới số Điều không tồn tại - loại bỏ tại chỗ (không phải
    suy diễn nội dung, chỉ lọc theo danh sách số hiệu có thật) và LOG rõ để phân biệt với
    trường hợp tham chiếu tới số hiệu CÓ THẬT nhưng sai ngữ nghĩa do lỗi đánh số trong chính
    văn bản gốc (loại lỗi này KHÔNG lọc được ở đây - xem log_relations_for_review).

    Args:
        extraction: Kết quả trích xuất từ LLM, được sửa TẠI CHỖ (in-place).
        valid_numbers: Tập số hiệu Điều/Khoản có thật trong hợp đồng.
    """
    for rel in extraction.clauses:
        for field in ("refers_to", "depends_on", "exception_to", "appendix_refs"):
            numbers = getattr(rel, field)
            invalid = [n for n in numbers if n not in valid_numbers]
            if invalid:
                logger.warning(
                    "Bỏ tham chiếu ảo giác: Clause %s.%s=%s trỏ tới số hiệu không tồn tại trong hợp đồng",
                    rel.clause_number, field, invalid,
                )
            setattr(rel, field, [n for n in numbers if n in valid_numbers])


def migrate_appendix_refs(extraction: ContractGraphExtraction) -> None:
    """Chuyển số hiệu Phụ lục (tiền tố "PL") lạc vào refers_to/depends_on/exception_to sang đúng
    appendix_refs - phòng thủ ở code thay vì chỉ tin prompt tuân thủ tuyệt đối (đã quan sát LLM
    ghi trùng cả 2 nơi dù prompt đã dặn KHÔNG điền vào 3 trường kia, xem mục "THAM CHIẾU TỚI PHỤ
    LỤC" trong system prompt) - đảm bảo appendix_refs luôn là NGUỒN DUY NHẤT cho quan hệ tới Phụ
    lục, không phụ thuộc việc LLM có tuân thủ tuyệt đối hay không.

    Args:
        extraction: Kết quả trích xuất từ LLM, được sửa TẠI CHỖ (in-place).
    """
    for rel in extraction.clauses:
        for field in ("refers_to", "depends_on", "exception_to"):
            numbers = getattr(rel, field)
            leaked = [n for n in numbers if n.startswith("PL")]
            if leaked:
                logger.warning(
                    "Chuyển số hiệu Phụ lục lạc từ %s sang appendix_refs: Clause %s.%s=%s",
                    field, rel.clause_number, field, leaked,
                )
                setattr(rel, field, [n for n in numbers if not n.startswith("PL")])
                rel.appendix_refs = sorted(set(rel.appendix_refs) | set(leaked))


def normalize_term(term: str) -> str:
    """Chuẩn hoá tên thuật ngữ để so khớp definitions<->uses_terms.

    Xử lý bất kể LLM có lỡ kèm dấu nháy đơn/kép bao quanh hay khoảng trắng thừa hay không
    (phòng thủ thêm ở code, không chỉ dựa vào prompt tuân thủ đúng định dạng "term không
    dấu nháy" đã yêu cầu).
    """
    return term.strip().strip("'\"‘’“”").strip()


def drop_invalid_uses_terms(extraction: ContractGraphExtraction) -> None:
    """Loại bỏ các uses_terms không khớp với bất kỳ definitions nào trong hợp đồng.

    Tương tự drop_invalid_references nhưng cho "uses_terms" - chỉ giữ thuật ngữ THẬT SỰ đã
    được định nghĩa ở đâu đó trong hợp đồng (gom từ "definitions" của mọi Clause), loại các
    thuật ngữ LLM "ảo giác" hoặc đánh vần lệch so với term gốc. Chuẩn hoá (normalize_term)
    TRƯỚC khi so khớp, và ghi lại cả definitions.term theo dạng đã chuẩn hoá để Neo4j lưu
    nhất quán.

    Args:
        extraction: Kết quả trích xuất từ LLM, được sửa TẠI CHỖ (in-place).
    """
    for rel in extraction.clauses:
        for d in rel.definitions:
            d.term = normalize_term(d.term)

    valid_terms = {d.term for rel in extraction.clauses for d in rel.definitions}
    for rel in extraction.clauses:
        normalized = [normalize_term(t) for t in rel.uses_terms]
        own_terms = {d.term for d in rel.definitions}
        invalid = [t for t in normalized if t not in valid_terms]
        if invalid:
            logger.warning(
                "Bỏ uses_terms ảo giác: Clause %s dùng thuật ngữ %s không khớp definitions nào trong hợp đồng",
                rel.clause_number, invalid,
            )
        rel.uses_terms = [t for t in normalized if t in valid_terms and t not in own_terms]


def log_relations_for_review(extraction: ContractGraphExtraction) -> None:
    """Log toàn bộ quan hệ chéo đã trích để người review tự xác minh.

    Log TOÀN BỘ quan hệ chéo đã trích (kèm clause_type 2 đầu) để người review phát hiện
    tham chiếu trỏ sai Clause do lỗi đánh số trong văn bản gốc (vd hợp đồng mẫu: Điều 11.3
    ghi "Điều 17.2" nhưng ý là "khoản 11.2"). KHÔNG tự động phán đoán đúng/sai (clause_type
    khác nhau không tự nó là dấu hiệu sai - 1 Điều có thể hợp lệ tham chiếu Điều khác loại),
    chỉ liệt kê đầy đủ để con người tự xác minh - tránh vừa thiếu sót (bỏ qua) vừa tự tin
    giả (heuristic đoán bừa).

    Args:
        extraction: Kết quả trích xuất đã trích, chỉ đọc (không sửa đổi).
    """
    type_by_number = {c.clause_number: c.clause_type for c in extraction.clauses}
    for rel in extraction.clauses:
        for field, rel_type in (
            ("refers_to", "REFERS_TO"), ("depends_on", "DEPENDS_ON"), ("exception_to", "EXCEPTION_TO"),
            ("appendix_refs", "REFERS_TO_APPENDIX"),
        ):
            for target in getattr(rel, field):
                logger.info(
                    "Quan hệ chéo: Clause %s (%s) -[%s]-> Clause %s (%s)",
                    rel.clause_number, rel.clause_type, rel_type, target, type_by_number.get(target, "?"),
                )
        for term in rel.uses_terms:
            logger.info("Quan hệ chéo: Clause %s (%s) -[USES_TERM]-> Definition '%s'", rel.clause_number, rel.clause_type, term)


def clause_label(c: dict) -> str:
    """Sinh nhãn hiển thị cho 1 Điều/Khoản/Phụ lục để đưa vào prompt LLM.

    Điều không có Khoản con hiển thị số hiệu Điều + tiêu đề ("[Điều 1. Định nghĩa]"); Điều
    có tách Khoản con thì mỗi Khoản hiển thị số hiệu "x.y" của nó (title Khoản chỉ là tiêu
    đề Điều cha mượn tạm để không rỗng - xem ingestion/section_splitter.py - nên phân biệt
    Điều/Khoản bằng number == article_number, không dựa vào title). Phụ lục
    (number="PL<nhãn>") cũng thoả number == article_number nên phải kiểm tra is_appendix
    TRƯỚC 2 nhánh trên - hiển thị NGUYÊN số hiệu nội bộ "PL<nhãn>" (không bỏ tiền tố "PL")
    để LLM ghi refers_to đúng y hệt số hiệu này, tránh phải tự suy luận quy tắc thêm/bớt
    tiền tố (dễ sai) - hậu tố "PL" chỉ ẩn đi ở tầng hiển thị cho người dùng cuối (xem
    rag/retrieval.py::Retrieval.build_context).

    Args:
        c: dict mô tả 1 Điều/Khoản/Phụ lục (number, title, article_number, is_appendix).

    Returns:
        Chuỗi nhãn để chèn trước nội dung Điều/Khoản trong prompt.
    """
    if c.get("is_appendix"):
        return f"[Phụ lục {c['number']}. {c['title']}]"
    if c["number"] == c["article_number"]:
        return f"[Điều {c['number']}. {c['title']}]"
    return f"[Khoản {c['number']}]"
