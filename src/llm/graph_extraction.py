"""Trích xuất tri thức pháp lý (các bên, luật áp dụng, quan hệ giữa các Điều) từ hợp đồng."""

from __future__ import annotations

import logging

from domain.entities.contract_graph import ContractGraphExtraction
from llm.client import get_chat_model
from llm.prompt_loader import load_prompt
from llm.usage import invoke_structured_with_usage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("contract_graph_extraction_prompt.txt")


def _drop_invalid_references(extraction: ContractGraphExtraction, valid_numbers: set[str]) -> None:
    """LLM đôi khi 'ảo giác' tham chiếu tới số Điều không tồn tại trong hợp đồng - loại bỏ
    tại chỗ (không phải suy diễn nội dung, chỉ lọc theo danh sách số hiệu có thật) và LOG rõ để
    phân biệt với trường hợp tham chiếu tới số hiệu CÓ THẬT nhưng sai ngữ nghĩa do lỗi đánh số
    trong chính văn bản gốc (loại lỗi này KHÔNG lọc được ở đây - xem _log_relations_for_review)."""
    for rel in extraction.clauses:
        for field in ("refers_to", "depends_on", "exception_to"):
            numbers = getattr(rel, field)
            invalid = [n for n in numbers if n not in valid_numbers]
            if invalid:
                logger.warning(
                    "Bỏ tham chiếu ảo giác: Clause %s.%s=%s trỏ tới số hiệu không tồn tại trong hợp đồng",
                    rel.clause_number, field, invalid,
                )
            setattr(rel, field, [n for n in numbers if n in valid_numbers])


def _normalize_term(term: str) -> str:
    """Chuẩn hoá tên thuật ngữ để so khớp definitions<->uses_terms bất kể LLM có lỡ kèm dấu nháy
    đơn/kép bao quanh hay khoảng trắng thừa hay không (phòng thủ thêm ở code, không chỉ dựa vào
    prompt tuân thủ đúng định dạng "term không dấu nháy" đã yêu cầu)."""
    return term.strip().strip("'\"‘’“”").strip()


def _drop_invalid_uses_terms(extraction: ContractGraphExtraction) -> None:
    """Tương tự _drop_invalid_references nhưng cho 'uses_terms' - chỉ giữ thuật ngữ THẬT SỰ đã
    được định nghĩa ở đâu đó trong hợp đồng (gom từ 'definitions' của mọi Clause), loại các thuật
    ngữ LLM 'ảo giác' hoặc đánh vần lệch so với term gốc. Chuẩn hoá (_normalize_term) TRƯỚC khi so
    khớp, và ghi lại cả definitions.term theo dạng đã chuẩn hoá để Neo4j lưu nhất quán."""
    for rel in extraction.clauses:
        for d in rel.definitions:
            d.term = _normalize_term(d.term)

    valid_terms = {d.term for rel in extraction.clauses for d in rel.definitions}
    for rel in extraction.clauses:
        normalized = [_normalize_term(t) for t in rel.uses_terms]
        own_terms = {d.term for d in rel.definitions}
        invalid = [t for t in normalized if t not in valid_terms]
        if invalid:
            logger.warning(
                "Bỏ uses_terms ảo giác: Clause %s dùng thuật ngữ %s không khớp definitions nào trong hợp đồng",
                rel.clause_number, invalid,
            )
        rel.uses_terms = [t for t in normalized if t in valid_terms and t not in own_terms]


def _log_relations_for_review(extraction: ContractGraphExtraction) -> None:
    """Log TOÀN BỘ quan hệ chéo đã trích (kèm clause_type 2 đầu) để người review phát hiện tham
    chiếu trỏ sai Clause do lỗi đánh số trong văn bản gốc (vd hợp đồng mẫu: Điều 11.3 ghi "Điều
    17.2" nhưng ý là "khoản 11.2"). KHÔNG tự động phán đoán đúng/sai (clause_type khác nhau không
    tự nó là dấu hiệu sai - 1 Điều có thể hợp lệ tham chiếu Điều khác loại), chỉ liệt kê đầy đủ để
    con người tự xác minh - tránh vừa thiếu sót (bỏ qua) vừa tự tin giả (heuristic đoán bừa)."""
    type_by_number = {c.clause_number: c.clause_type for c in extraction.clauses}
    for rel in extraction.clauses:
        for field, rel_type in (("refers_to", "REFERS_TO"), ("depends_on", "DEPENDS_ON"), ("exception_to", "EXCEPTION_TO")):
            for target in getattr(rel, field):
                logger.info(
                    "Quan hệ chéo: Clause %s (%s) -[%s]-> Clause %s (%s)",
                    rel.clause_number, rel.clause_type, rel_type, target, type_by_number.get(target, "?"),
                )
        for term in rel.uses_terms:
            logger.info("Quan hệ chéo: Clause %s (%s) -[USES_TERM]-> Definition '%s'", rel.clause_number, rel.clause_type, term)


def _clause_label(c: dict) -> str:
    """Điều không có Khoản con hiển thị số hiệu Điều + tiêu đề ("[Điều 1. Định nghĩa]"); Điều có
    tách Khoản con thì mỗi Khoản hiển thị số hiệu 'x.y' của nó (title Khoản chỉ là tiêu đề Điều
    cha mượn tạm để không rỗng - xem ingestion/section_splitter.py - nên phân biệt Điều/Khoản
    bằng number == article_number, không dựa vào title)."""
    if c["number"] == c["article_number"]:
        return f"[Điều {c['number']}. {c['title']}]"
    return f"[Khoản {c['number']}]"


def extract_relations(contract_name: str, clauses: list[dict]) -> tuple[ContractGraphExtraction, dict]:
    """Trả về (extraction, usage_info) - usage_info giờ được track thật (trước đây lệnh LLM này
    gọi thẳng structured_model.invoke() không qua invoke_structured_with_usage() nên KHÔNG có
    thông tin chi phí, dù đây là lệnh LLM đắt nhất trong pipeline - cả hợp đồng trong 1 lần gọi)."""
    clauses_block = "\n\n".join(f"{_clause_label(c)}\n{c['text']}" for c in clauses)
    user_content = f"Hợp đồng '{contract_name}', danh sách các Điều:\n\n{clauses_block}"

    logger.info("Gọi LLM trích xuất quan hệ hợp đồng '%s', n_clauses=%d, input_len=%d", contract_name, len(clauses), len(user_content))
    extraction, usage = invoke_structured_with_usage(get_chat_model(), _SYSTEM_PROMPT, user_content, ContractGraphExtraction)

    valid_numbers = {c["number"] for c in clauses}
    _drop_invalid_references(extraction, valid_numbers)
    _drop_invalid_uses_terms(extraction)
    _log_relations_for_review(extraction)
    logger.info(
        "Hoàn tất trích xuất quan hệ hợp đồng '%s', n_clause_relations=%d, usage=%s",
        contract_name, len(extraction.clauses), usage,
    )
    return extraction, usage
