"""Xây dựng graph tri thức của hợp đồng trong Neo4j.

Câu lệnh Cypher nằm trong knowledge_graph/queries.py - file này chỉ lo điều phối logic Python (chuẩn bị
tham số, gọi query theo đúng thứ tự phụ thuộc)."""

from __future__ import annotations

import logging

from config.settings import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from domain.entities.contract_graph import ContractGraphExtraction
from knowledge_graph.client import get_graph
from knowledge_graph.queries import (
    CLEAR_GRAPH,
    CREATE_AGREEMENT,
    CREATE_CLAUSE_RELATIONS,
    CREATE_CLAUSE_USES_TERM,
    CREATE_CLAUSES,
    CREATE_DEFINITIONS,
    CREATE_DISPUTE_RESOLUTION,
    CREATE_EXCERPTS,
    CREATE_GOVERNING_LAW,
    CREATE_PARTIES,
    CREATE_SECTIONS,
    CREATE_VECTOR_INDEX,
    DELETE_CONTRACT,
    NEXT_CONTRACT_ID,
    SET_AGREEMENT_BUILD_COST,
    SET_EXCERPT_EMBEDDING,
)
from knowledge_graph.schema_migration import ensure_schema
from ingestion.excerpt_splitter import split_clause_into_excerpts
from llm.embeddings import get_embeddings
from llm.usage import estimate_embedding_usage, sum_usage

logger = logging.getLogger(__name__)


def clear_graph() -> None:
    """Xoá SẠCH TOÀN BỘ graph, mọi hợp đồng - chỉ dùng cho việc dọn dẹp thủ công/dev, KHÔNG được
    gọi tự động khi import 1 hợp đồng (xem delete_contract() cho việc xoá riêng 1 hợp đồng)."""
    logger.warning("Xoá SẠCH TOÀN BỘ graph (mọi hợp đồng)")
    get_graph().query(CLEAR_GRAPH)
    logger.info("Đã xoá sạch toàn bộ graph")


def delete_contract(contract_id: int) -> None:
    """Xoá riêng 1 hợp đồng (mọi node mang agreement_id = contract_id, kể cả Agreement) - không
    ảnh hưởng các hợp đồng khác vì mọi node đều được scope theo agreement_id."""
    logger.info("Bắt đầu xoá graph của hợp đồng, contract_id=%s", contract_id)
    get_graph().query(DELETE_CONTRACT, params={"contract_id": contract_id})
    logger.info("Hoàn tất xoá graph của hợp đồng, contract_id=%s", contract_id)


def next_contract_id() -> int:
    """Số hiệu hợp đồng mới, tăng dần - dùng khi import 1 hợp đồng mới (không ghi đè hợp đồng cũ)."""
    records = get_graph().query(NEXT_CONTRACT_ID)
    return records[0]["next_id"]


def build_graph(
    contract_id: int,
    contract_name: str,
    sections: list[dict],
    clauses: list[dict],
    extraction: ContractGraphExtraction,
    extraction_usage: dict,
    source_filename: str = "",
) -> int:
    """Trả về số quan hệ chéo (REFERS_TO/DEPENDS_ON/EXCEPTION_TO) đã tạo.

    source_filename: tên file gốc KÈM ĐUÔI (vd "hop_dong.pdf") - lưu riêng vì contract_name là
    tên hiển thị (đã bỏ đuôi file) nên không đủ để UI suy ra định dạng file khi tải lại trang.
    extraction_usage: usage_info của lệnh LLM trích xuất quan hệ (từ llm.graph_extraction.
    extract_relations) - gộp với chi phí embedding (tính trong hàm này) rồi lưu tổng vào Agreement
    node (SET_AGREEMENT_BUILD_COST), xem llm/usage.py."""
    logger.info(
        "Bắt đầu tạo graph hợp đồng, contract_id=%s, name=%s, n_sections=%d, n_clauses=%d",
        contract_id, contract_name, len(sections), len(clauses),
    )
    graph = get_graph()
    ensure_schema(graph)
    relations_by_number = {r.clause_number: r for r in extraction.clauses}

    clause_number_to_section = {}
    for s in sections:
        for cn in s["clause_numbers"]:
            clause_number_to_section[cn] = s["number"]

    clause_rows = []
    definition_rows = []
    for c in clauses:
        rel = relations_by_number.get(c["number"])
        is_preamble = c.get("is_preamble", False)
        default_type = "Thông tin chung và các bên tham gia hợp đồng" if is_preamble else "Khác"
        clause_rows.append(
            {
                "number": c["number"],
                "title": c["title"],
                "text": c["text"],
                "section_number": clause_number_to_section.get(c["number"], sections[0]["number"]),
                "clause_type": rel.clause_type if rel else default_type,
                "is_preamble": is_preamble,
                # Khoản 'x.y' tự nó không có tiêu đề (chỉ Điều mới có) - giữ lại số hiệu/tiêu đề
                # Điều cha để UI hiển thị ngữ cảnh (vd "Điều 1. ĐỐI TƯỢNG HỢP ĐỒNG › Khoản 1.2"),
                # không hiện trơ trọi "1.2" không rõ thuộc Điều nào.
                "article_number": c.get("article_number", c["number"]),
                "article_title": c.get("article_title", c["title"]),
            }
        )
        if rel:
            for d in rel.definitions:
                definition_rows.append({"clause_number": c["number"], "term": d.term, "definition": d.definition})

    graph.query(
        CREATE_AGREEMENT,
        params={"contract_id": contract_id, "contract_name": contract_name, "source_filename": source_filename},
    )
    graph.query(
        CREATE_PARTIES,
        params={"contract_id": contract_id, "parties": [p.model_dump() for p in extraction.parties]},
    )
    graph.query(
        CREATE_GOVERNING_LAW,
        params={"contract_id": contract_id, "governing_law": extraction.governing_law.model_dump()},
    )
    graph.query(
        CREATE_DISPUTE_RESOLUTION,
        params={"contract_id": contract_id, "dispute_resolution": extraction.dispute_resolution.model_dump()},
    )
    graph.query(CREATE_SECTIONS, params={"contract_id": contract_id, "sections": sections})
    graph.query(CREATE_CLAUSES, params={"contract_id": contract_id, "clauses": clause_rows})
    if definition_rows:
        graph.query(CREATE_DEFINITIONS, params={"contract_id": contract_id, "definitions": definition_rows})

    # USES_TERM phải tạo SAU CREATE_DEFINITIONS (Definition node cần tồn tại trước để MATCH) - chỉ
    # tạo quan hệ cho thuật ngữ THẬT ĐÃ được định nghĩa trong hợp đồng (đã lọc ở graph_extraction.py).
    uses_term_rows = [
        {"clause_number": r.clause_number, "term": term} for r in extraction.clauses for term in r.uses_terms
    ]
    if uses_term_rows:
        graph.query(CREATE_CLAUSE_USES_TERM, params={"contract_id": contract_id, "uses": uses_term_rows})

    excerpt_rows = []
    for c in clause_rows:
        for chunk_index, excerpt_text in enumerate(split_clause_into_excerpts(c["text"])):
            excerpt_rows.append(
                {
                    "clause_number": c["number"],
                    "chunk_index": chunk_index,
                    "text": excerpt_text,
                    "is_preamble": c["is_preamble"],
                }
            )
    graph.query(CREATE_EXCERPTS, params={"contract_id": contract_id, "excerpts": excerpt_rows})

    cross_relations = []
    for r in extraction.clauses:
        for target in r.refers_to:
            cross_relations.append({"from": r.clause_number, "to": target, "type": "REFERS_TO"})
        for target in r.depends_on:
            cross_relations.append({"from": r.clause_number, "to": target, "type": "DEPENDS_ON"})
        for target in r.exception_to:
            cross_relations.append({"from": r.clause_number, "to": target, "type": "EXCEPTION_TO"})

    if cross_relations:
        graph.query(CREATE_CLAUSE_RELATIONS, params={"contract_id": contract_id, "relations": cross_relations})

    graph.query(CREATE_VECTOR_INDEX, params={"dimensions": EMBEDDING_DIMENSIONS})

    excerpt_texts = [e["text"] for e in excerpt_rows]
    vectors = get_embeddings().embed_texts(excerpt_texts)
    embedding_rows = [
        {"uid": f"{contract_id}:{e['clause_number']}:{e['chunk_index']}", "embedding": vector}
        for e, vector in zip(excerpt_rows, vectors)
    ]
    graph.query(SET_EXCERPT_EMBEDDING, params={"rows": embedding_rows})

    embedding_usage = estimate_embedding_usage(EMBEDDING_MODEL, excerpt_texts)
    build_usage = sum_usage(extraction_usage, embedding_usage)
    graph.query(SET_AGREEMENT_BUILD_COST, params={"contract_id": contract_id, **build_usage})

    logger.info(
        "Hoàn tất tạo graph hợp đồng, contract_id=%s, n_clauses=%d, n_excerpts=%d, n_cross_relations=%d, "
        "n_definitions=%d, n_uses_term=%d, build_usage=%s",
        contract_id, len(clause_rows), len(excerpt_rows), len(cross_relations), len(definition_rows),
        len(uses_term_rows), build_usage,
    )

    return len(cross_relations)
