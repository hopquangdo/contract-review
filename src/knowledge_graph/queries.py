"""Toàn bộ câu lệnh Cypher dùng trong ứng dụng - gom về 1 nơi để dễ soát khi đổi schema, tách
khỏi logic Python (build graph, retrieval, nghiệp vụ hợp đồng) của từng module gọi tới."""

from __future__ import annotations

# ─────────────────────────── knowledge_graph/builder.py ───────────────────────────
# Mỗi bước tạo node/quan hệ là 1 câu lệnh riêng biệt, không gộp chung nhiều UNWIND trong cùng 1
# query, để tránh nhân tích luỹ (Cartesian) giữa các UNWIND.

CREATE_AGREEMENT = """
MERGE (agreement:Agreement {contract_id: $contract_id})
ON CREATE SET agreement.name = $contract_name, agreement.source_filename = $source_filename
"""

# Chi phí build graph (LLM trích xuất quan hệ + embedding toàn bộ Excerpt) - ghi SAU khi build
# xong (embedding cost chỉ biết được sau khi embed_texts() chạy) - xem knowledge_graph/builder.py.
SET_AGREEMENT_BUILD_COST = """
MATCH (agreement:Agreement {contract_id: $contract_id})
SET agreement.build_input_tokens = $input_tokens,
    agreement.build_output_tokens = $output_tokens,
    agreement.build_cost_usd = $cost_usd
"""

CREATE_PARTIES = """
MATCH (agreement:Agreement {contract_id: $contract_id})
UNWIND $parties AS p
MERGE (org:Organization {uid: toString($contract_id) + ':' + p.name})
SET org.agreement_id = $contract_id, org.name = p.name
MERGE (agreement)-[hp:HAS_PARTY]->(org)
SET hp.role = p.role
"""

CREATE_GOVERNING_LAW = """
MATCH (agreement:Agreement {contract_id: $contract_id})
MERGE (gl:GoverningLaw {uid: toString($contract_id) + ':governing_law'})
SET gl.agreement_id = $contract_id, gl.country = $governing_law.country, gl.state = $governing_law.state
MERGE (agreement)-[:GOVERNED_BY]->(gl)
"""

CREATE_DISPUTE_RESOLUTION = """
MATCH (agreement:Agreement {contract_id: $contract_id})
MERGE (dr:DisputeResolution {uid: toString($contract_id) + ':dispute_resolution'})
SET dr.agreement_id = $contract_id, dr.method = $dispute_resolution.method, dr.venue = $dispute_resolution.venue
MERGE (agreement)-[:HAS_DISPUTE_RULE]->(dr)
"""

CREATE_SECTIONS = """
MATCH (agreement:Agreement {contract_id: $contract_id})
UNWIND $sections AS s
MERGE (section:Section {number: s.number, agreement_id: $contract_id})
ON CREATE SET section.title = s.title
MERGE (agreement)-[:HAS_SECTION]->(section)
"""

CREATE_CLAUSES = """
UNWIND $clauses AS cl
MATCH (section:Section {number: cl.section_number, agreement_id: $contract_id})
MERGE (clause:Clause {uid: toString($contract_id) + ':' + cl.number})
SET clause.number = cl.number, clause.agreement_id = $contract_id,
    clause.title = cl.title, clause.text = cl.text, clause.is_preamble = cl.is_preamble,
    clause.article_number = cl.article_number, clause.article_title = cl.article_title
MERGE (section)-[:HAS_CLAUSE]->(clause)
MERGE (ct:ClauseType {uid: toString($contract_id) + ':' + cl.clause_type})
SET ct.agreement_id = $contract_id, ct.name = cl.clause_type
MERGE (clause)-[:HAS_TYPE]->(ct)
"""

# 1 Clause có thể có NHIỀU Excerpt (Điều/Khoản dài được tách thêm - xem
# ingestion/excerpt_splitter.py) - excerpt_rows đã được tính sẵn ở Python, mỗi Excerpt biết rõ
# clause_number cha để MATCH đúng Clause, không suy luận trong Cypher.
CREATE_EXCERPTS = """
UNWIND $excerpts AS ex
MATCH (clause:Clause {number: ex.clause_number, agreement_id: $contract_id})
MERGE (excerpt:Excerpt {uid: toString($contract_id) + ':' + ex.clause_number + ':' + toString(ex.chunk_index)})
SET excerpt.agreement_id = $contract_id, excerpt.clause_number = ex.clause_number,
    excerpt.chunk_index = ex.chunk_index, excerpt.text = ex.text, excerpt.is_preamble = ex.is_preamble
MERGE (clause)-[:HAS_EXCERPT]->(excerpt)
"""

CREATE_DEFINITIONS = """
UNWIND $definitions AS d
MATCH (clause:Clause {number: d.clause_number, agreement_id: $contract_id})
MERGE (def:Definition {uid: toString($contract_id) + ':' + d.term})
SET def.agreement_id = $contract_id, def.term = d.term, def.definition = d.definition
MERGE (clause)-[:DEFINES]->(def)
"""

CREATE_CLAUSE_USES_TERM = """
UNWIND $uses AS u
MATCH (clause:Clause {number: u.clause_number, agreement_id: $contract_id})
MATCH (def:Definition {uid: toString($contract_id) + ':' + u.term})
MERGE (clause)-[:USES_TERM]->(def)
"""

CREATE_CLAUSE_RELATIONS = """
UNWIND $relations AS rel
MATCH (from:Clause {number: rel.from, agreement_id: $contract_id})
MATCH (to:Clause {number: rel.to, agreement_id: $contract_id})
CALL apoc.merge.relationship(from, rel.type, {}, {}, to) YIELD rel AS r
RETURN count(r)
"""

CREATE_VECTOR_INDEX = """
CREATE VECTOR INDEX excerpt_embedding IF NOT EXISTS
    FOR (e:Excerpt) ON (e.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: $dimensions, `vector.similarity_function`: 'cosine'}}
"""

SET_EXCERPT_EMBEDDING = """
UNWIND $rows AS row
MATCH (e:Excerpt {uid: row.uid})
SET e.embedding = row.embedding
"""

CLEAR_GRAPH = "MATCH (n) DETACH DELETE n"

DELETE_CONTRACT = """
MATCH (n) WHERE n.agreement_id = $contract_id OR n.contract_id = $contract_id DETACH DELETE n
"""

NEXT_CONTRACT_ID = "MATCH (a:Agreement) RETURN coalesce(max(a.contract_id), 0) + 1 AS next_id"


# ─────────────────────────── rag/retrieval/vector_retriever.py ───────────────────────────

# Clause có is_preamble=True (phần mở đầu hợp đồng: các bên, người đại diện/chức vụ, ngày ký...)
# là context NỀN, luôn liên quan tới hầu hết mọi câu hỏi (vd: "người ký có đúng thẩm quyền" cần
# biết ai ký/chức vụ gì) nhưng có thể KHÔNG lọt vào top-k theo similarity nếu câu hỏi không đủ
# giống về từ ngữ - nên luôn đính kèm, không phụ thuộc vector search. Xem ingestion/section_splitter.py.
GET_PREAMBLE_CLAUSE = """
MATCH (clause:Clause {agreement_id: $contract_id, is_preamble: true})
WITH clause LIMIT 1
MATCH (clause)-[:HAS_EXCERPT]->(excerpt:Excerpt)
RETURN clause.number AS number, clause.title AS title, clause.article_number AS article_number,
       clause.article_title AS article_title, excerpt.chunk_index AS chunk_index, excerpt.text AS text
ORDER BY excerpt.chunk_index
"""

# Trả kèm chunk_index của Excerpt đã khớp - dùng để biết CHÍNH XÁC Excerpt nào trong Clause đã
# match với câu hỏi, khi ghép lại với toàn bộ Excerpt của Clause đó (xem GET_CLAUSE_EXCERPTS).
# Filter theo agreement_id/is_preamble (property có sẵn trên Excerpt, xem CREATE_EXCERPTS ở trên)
# khiến Neo4jVector chuyển sang quét đủ (exhaustive scan có điều kiện) thay vì dùng ANN index
# toàn cục, đảm bảo top-k luôn đúng phạm vi 1 hợp đồng thay vì bị các hợp đồng khác lấn kết quả.
VECTOR_RETRIEVAL = """
MATCH (node)<-[:HAS_EXCERPT]-(clause:Clause)
RETURN clause.text AS text, score,
       {number: clause.number, title: clause.title, article_number: clause.article_number,
        article_title: clause.article_title, chunk_index: node.chunk_index} AS metadata
"""

# Lấy lại TOÀN BỘ Excerpt (không chỉ Excerpt đã khớp) của các Clause được chọn vào top-k - để
# hiển thị đúng cấu trúc graph thật (Clause -[:HAS_EXCERPT]-> nhiều Excerpt) thay vì gộp phẳng
# thành 1 khối text duy nhất.
GET_CLAUSE_EXCERPTS = """
UNWIND $numbers AS num
MATCH (clause:Clause {agreement_id: $contract_id, number: num})-[:HAS_EXCERPT]->(excerpt:Excerpt)
RETURN clause.number AS number, excerpt.chunk_index AS chunk_index, excerpt.text AS text
"""

# Thông tin cơ bản (không phải text đầy đủ) của 1 tập Clause theo số hiệu - dùng khi cần biết
# title/article_number/article_title cho cả Clause KHÔNG nằm trong kết quả vector search (vd
# các Khoản anh em cùng Điều được kéo thêm bởi rag/retrieval/expansion.py).
GET_CLAUSES_INFO = """
UNWIND $numbers AS num
MATCH (c:Clause {agreement_id: $contract_id, number: num})
RETURN c.number AS number, c.title AS title, c.article_number AS article_number,
       c.article_title AS article_title
"""

# Toàn bộ Clause thuộc 1 hoặc nhiều Điều (article_number) - dùng cho chiến lược mở rộng "kéo
# theo cả Điều" (xem rag/retrieval/expansion.py) khi 1 Khoản khớp câu hỏi.
GET_SIBLING_CLAUSE_NUMBERS = """
UNWIND $article_numbers AS art
MATCH (c:Clause {agreement_id: $contract_id, article_number: art, is_preamble: false})
RETURN c.number AS number
"""

# Metadata cấp Hợp đồng (luật áp dụng, phương thức giải quyết tranh chấp) - luôn đính kèm context
# LLM giống preamble, KHÔNG qua vector search (đây là fact tra cứu trực tiếp 1-1 theo contract_id,
# không phải nội dung cần "tìm kiếm" mức độ liên quan). GoverningLaw/DisputeResolution trước đây
# chỉ được ghi lúc build (CREATE_GOVERNING_LAW/CREATE_DISPUTE_RESOLUTION) mà chưa từng đọc lại.
GET_AGREEMENT_METADATA = """
MATCH (a:Agreement {contract_id: $contract_id})
OPTIONAL MATCH (a)-[:GOVERNED_BY]->(gl:GoverningLaw)
OPTIONAL MATCH (a)-[:HAS_DISPUTE_RULE]->(dr:DisputeResolution)
RETURN gl.country AS governing_law_country, gl.state AS governing_law_state,
       dr.method AS dispute_method, dr.venue AS dispute_venue
"""

# Các Clause liên quan tới 1 tập Clause đã khớp qua quan hệ chéo (REFERS_TO/DEPENDS_ON/
# EXCEPTION_TO - tạo trong CREATE_CLAUSE_RELATIONS) - không phân biệt chiều quan hệ (match cả 2
# hướng "-[r]-") vì cả 2 phía đều là ngữ cảnh hữu ích khi 1 trong 2 đã khớp câu hỏi. Dùng cho
# query-aware expansion (xem rag/retrieval/expansion.py::expand_by_relations) - chỉ chạy với tập
# relation_types phù hợp với loại câu hỏi, không lấy tất cả mọi loại quan hệ tràn lan.
GET_RELATED_CLAUSE_NUMBERS = """
UNWIND $numbers AS num
MATCH (c:Clause {agreement_id: $contract_id, number: num})-[r]-(other:Clause {agreement_id: $contract_id})
WHERE type(r) IN $relation_types
RETURN DISTINCT other.number AS number
"""

# Clause ĐỊNH NGHĨA (DEFINES) các thuật ngữ mà 1 tập Clause đã chọn có SỬ DỤNG (USES_TERM) - kéo
# theo định nghĩa gốc để LLM không phải đoán nghĩa thuật ngữ khi Khoản trích dẫn chỉ nhắc tới mà
# không tự định nghĩa lại (xem rag/retrieval/expansion.py::expand_by_definitions).
GET_CLAUSES_DEFINING_USED_TERMS = """
UNWIND $numbers AS num
MATCH (c:Clause {agreement_id: $contract_id, number: num})-[:USES_TERM]->(def:Definition)<-[:DEFINES]-(source:Clause)
RETURN DISTINCT source.number AS number
"""


# ─────────────────────────── services/contract_service.py ───────────────────────────

GET_CONTRACT_STATUS = """
MATCH (a:Agreement {contract_id: $id})
OPTIONAL MATCH (a)-[:HAS_SECTION]->(:Section)-[:HAS_CLAUSE]->(c:Clause)
RETURN a.contract_id AS contract_id, a.name AS name, a.source_filename AS source_filename,
       count(c) AS n_clauses
"""

LIST_CONTRACTS = """
MATCH (a:Agreement)
OPTIONAL MATCH (a)-[:HAS_SECTION]->(:Section)-[:HAS_CLAUSE]->(c:Clause)
RETURN a.contract_id AS contract_id, a.name AS name, a.source_filename AS source_filename,
       count(c) AS n_clauses
ORDER BY a.contract_id
"""
