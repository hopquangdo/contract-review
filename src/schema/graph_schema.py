"""Schema Neo4j của graph hợp đồng: node label + property chính, loại quan hệ, và constraint/index -
gộp 3 khía cạnh cùng 1 khái niệm "cấu trúc graph thật đang chạy" vào 1 file. Nguồn sự thật DUY NHẤT
vẫn là các câu Cypher trong `knowledge_graph/queries.py` - sửa schema thì sửa ở đó, rồi cập nhật lại
NODE_LABELS/STRUCTURAL_RELATIONSHIPS/SEMANTIC_RELATIONSHIPS/DERIVED_RELATIONSHIPS cho khớp.

NODE_LABELS/STRUCTURAL_RELATIONSHIPS/SEMANTIC_RELATIONSHIPS/DERIVED_RELATIONSHIPS là tài liệu tham
chiếu - KHÔNG nơi nào import (không phải dead code cần dọn), chỉ để tra cứu nhanh schema thật đang
chạy mà không phải đọc lại toàn bộ queries.py. `ensure_schema()` là hàm THẬT SỰ được gọi (đầu mỗi
lần build_graph()) để tạo constraint/index nếu chưa có."""

from __future__ import annotations

import logging

from langchain_neo4j import Neo4jGraph

logger = logging.getLogger(__name__)

# Mỗi entry: label -> {"key": property định danh duy nhất, "properties": các property chính khác}.
NODE_LABELS: dict[str, dict[str, object]] = {
    "Agreement": {"key": "contract_id", "properties": ["name", "source_filename", "build_input_tokens", "build_output_tokens", "build_cost_usd"]},
    "Section": {"key": "(number, agreement_id)", "properties": ["title"]},
    "Clause": {"key": "uid", "properties": ["number", "agreement_id", "title", "text", "is_preamble", "is_appendix", "article_number", "article_title"]},
    "Excerpt": {"key": "uid", "properties": ["agreement_id", "clause_number", "chunk_index", "text", "is_preamble", "embedding"]},
    "Definition": {"key": "uid", "properties": ["agreement_id", "term", "definition"]},
    "ClauseType": {"key": "uid", "properties": ["agreement_id", "name"]},
    "Organization": {"key": "uid", "properties": ["agreement_id", "name"]},
    "GoverningLaw": {"key": "uid", "properties": ["agreement_id", "country", "state"]},
    "DisputeResolution": {"key": "uid", "properties": ["agreement_id", "method", "venue"]},
}

# Quan hệ CẤU TRÚC (structural) - luôn tồn tại, không tuỳ thuộc nội dung hợp đồng.
STRUCTURAL_RELATIONSHIPS: dict[str, str] = {
    "HAS_SECTION": "Agreement -> Section",
    "HAS_CLAUSE": "Section -> Clause",
    "HAS_EXCERPT": "Clause -> Excerpt",
    "HAS_TYPE": "Clause -> ClauseType",
    "HAS_PARTY": "Agreement -> Organization (kèm property 'role')",
    "GOVERNED_BY": "Agreement -> GoverningLaw",
    "HAS_DISPUTE_RULE": "Agreement -> DisputeResolution",
}

# Quan hệ NGỮ NGHĨA (semantic) - do LLM trích xuất từ nội dung hợp đồng (knowledge_graph/graph.py::
# Graph.extract_relations), KHÔNG cố định số lượng, cả 2 chiều đều là ngữ cảnh hợp lệ khi mở
# rộng graph (xem knowledge_graph/graph.py::Graph.expand_by_relations).
SEMANTIC_RELATIONSHIPS: dict[str, str] = {
    "DEFINES": "Clause -> Definition",
    "USES_TERM": "Clause -> Definition (Clause khác dùng thuật ngữ đã DEFINES ở Clause khác)",
    "REFERS_TO": "Clause -> Clause (dẫn chiếu)",
    "DEPENDS_ON": "Clause -> Clause (phụ thuộc)",
    "EXCEPTION_TO": "Clause -> Clause (ngoại lệ của)",
    "REFERS_TO_APPENDIX": "Clause -> Clause (Phụ lục, thường trỏ vào node GỐC Phụ lục)",
}

# CONTAINS (gốc Phụ lục -> mục con Phụ lục) KHÔNG phải cạnh Neo4j thật - tự dựng lúc truy hồi (chỉ
# dựa vào cùng article_number), xem rag/builder.py.
DERIVED_RELATIONSHIPS: dict[str, str] = {
    "CONTAINS": "Phụ lục gốc -> mục con Phụ lục (suy ra lúc truy hồi, không lưu trong Neo4j)",
}

_DROP_STATEMENTS = [
    # Ràng buộc cũ (unique theo "name" trần) từ trước khi hỗ trợ nhiều hợp đồng - phải xoá vì
    # giờ đây "name" được phép trùng giữa các hợp đồng khác nhau, chỉ "uid" (có tiền tố
    # contract_id) mới cần duy nhất.
    "DROP CONSTRAINT clausetype_name IF EXISTS",
    "DROP CONSTRAINT org_name IF EXISTS",
]

_STATEMENTS = [
    "CREATE CONSTRAINT agreement_id IF NOT EXISTS FOR (a:Agreement) REQUIRE a.contract_id IS UNIQUE",
    "CREATE CONSTRAINT clause_uid IF NOT EXISTS FOR (c:Clause) REQUIRE c.uid IS UNIQUE",
    "CREATE CONSTRAINT excerpt_uid IF NOT EXISTS FOR (e:Excerpt) REQUIRE e.uid IS UNIQUE",
    "CREATE CONSTRAINT definition_uid IF NOT EXISTS FOR (d:Definition) REQUIRE d.uid IS UNIQUE",
    "CREATE CONSTRAINT clausetype_uid IF NOT EXISTS FOR (ct:ClauseType) REQUIRE ct.uid IS UNIQUE",
    "CREATE CONSTRAINT org_uid IF NOT EXISTS FOR (o:Organization) REQUIRE o.uid IS UNIQUE",
    "CREATE CONSTRAINT governinglaw_uid IF NOT EXISTS FOR (gl:GoverningLaw) REQUIRE gl.uid IS UNIQUE",
    "CREATE CONSTRAINT disputeresolution_uid IF NOT EXISTS FOR (dr:DisputeResolution) REQUIRE dr.uid IS UNIQUE",
    "CREATE INDEX clause_agreement_idx IF NOT EXISTS FOR (c:Clause) ON (c.agreement_id)",
]


def ensure_schema(graph: Neo4jGraph) -> None:
    """Tạo constraint/index nếu chưa có, xoá constraint cũ không còn phù hợp.

    Gọi ở đầu mỗi lần build_graph().

    Args:
        graph: Instance Neo4jGraph đang kết nối tới database cần migrate.
    """
    logger.info("Bắt đầu migration schema Neo4j (constraint/index)")
    for statement in _DROP_STATEMENTS:
        graph.query(statement)
    for statement in _STATEMENTS:
        graph.query(statement)
    logger.info("Hoàn tất migration schema Neo4j (constraint/index)")
