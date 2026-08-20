"""Kết nối/truy vấn/ghi TRỰC TIẾP Neo4j (vector index "excerpt_embedding" + graph traversal các
quan hệ REFERS_TO/DEPENDS_ON/EXCEPTION_TO..., tạo/xoá/xuất graph tri thức hợp đồng, trích xuất quan
hệ pháp lý bằng LLM) - tách khỏi phần orchestration (chọn lọc theo ngưỡng, gộp nhiều truy vấn...)
vốn thuộc về tầng `rag/` (business logic), để `knowledge_graph/` chỉ còn đúng việc "nói chuyện với
Neo4j" (kể cả bước LLM trích xuất quan hệ - dù bản thân extract_relations() không gọi Neo4j trực
tiếp, kết quả của nó CHỈ được dùng để build_graph(), nên gộp vào cùng 1 chỗ cho toàn bộ luồng "tạo
graph 1 hợp đồng" nằm trong 1 class).

Mỗi phương thức mở rộng (expand_by_*) nhận vào (contract_id, danh sách Clause đã khớp) và trả về
danh sách CẠNH {"number": <số hiệu Clause cần lấy thêm>, "from": <số hiệu Clause là nguồn THẬT của
quan hệ>, "to": <số hiệu Clause là đích THẬT của quan hệ>, "relation": <loại quan hệ - tên quan hệ
Neo4j thật hoặc nhãn suy ra "SAME_ARTICLE"/"CONTAINS">. "from"/"to" theo ĐÚNG chiều lưu trong Neo4j
(không phải chiều truy vấn) - vì GET_RELATED_CLAUSE_NUMBERS match KHÔNG phân biệt chiều (-[r]-) để
không bỏ sót ngữ cảnh 2 phía, nhưng khi dựng cây "evidences" (lộ nguyên nhân đồ thị) phải hiển thị
đúng chiều thật (vd "Điều 14 dẫn chiếu tới Phụ lục 03", không phải ngược lại) - "number" luôn là
phía KHÁC với Clause đã truy vấn (dùng để nạp thêm vào numbers_to_load), còn "from"/"to" mới là cặp
dùng để dựng cây đúng hướng ở vector_retriever.py."""

from __future__ import annotations

import logging

from langchain_neo4j import Neo4jVector

from config.settings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    GRAPH_EXTRACTION_MODEL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
)
from knowledge_graph.client import get_graph
from helpers.excerpt_splitting import split_clause_into_excerpts_llm
from helpers.graph_extraction import (
    clause_label,
    drop_invalid_references,
    drop_invalid_uses_terms,
    log_relations_for_review,
    migrate_appendix_refs,
)
from knowledge_graph.queries import (
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
    GET_CLAUSES_DEFINING_USED_TERMS,
    GET_RELATED_CLAUSE_NUMBERS,
    NEXT_CONTRACT_ID,
    SET_AGREEMENT_BUILD_COST,
    SET_EXCERPT_EMBEDDING,
    VECTOR_RETRIEVAL,
)
from schema.graph_schema import ensure_schema
from llm.embeddings import get_embeddings
from llm.usage import estimate_embedding_usage, invoke_structured_with_usage, sum_usage
from schema.contract import ContractGraphExtraction
from utils.prompt_loader import load_prompt
from utils.text_cleanup import snippet

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = load_prompt("contract_graph_extraction_prompt.txt")

_CROSS_RELATION_TYPES = ["REFERS_TO", "DEPENDS_ON", "EXCEPTION_TO", "REFERS_TO_APPENDIX"]


class Graph:
    """Gộp toàn bộ giao tiếp với Neo4j của hợp đồng vào một chỗ: vector search (Neo4jVector index
    "excerpt_embedding"), graph traversal (mở rộng tập Clause sau khi vector search đã chọn ra
    top-k), tạo/xoá/xuất graph tri thức 1 hợp đồng, và bước LLM trích xuất quan hệ pháp lý (đầu vào
    của build_graph) - tách riêng để thêm/đổi chiến lược trong tương lai không phải sửa logic truy
    hồi cốt lõi ở `rag/`."""

    def __init__(self) -> None:
        self._vector_store: Neo4jVector | None = None

    def get_vector_store(self) -> Neo4jVector:
        """Trả về (và khởi tạo lazy nếu cần) Neo4jVector store dùng chung cho index "excerpt_embedding"."""
        if self._vector_store is None:
            get_graph()  # garante driver/index đã sẵn sàng (index tạo trong build_graph())
            self._vector_store = Neo4jVector.from_existing_index(
                embedding=get_embeddings().as_langchain_embeddings(),
                url=NEO4J_URI,
                username=NEO4J_USERNAME,
                password=NEO4J_PASSWORD,
                index_name="excerpt_embedding",
                node_label="Excerpt",
                text_node_property="text",
                embedding_node_property="embedding",
                retrieval_query=VECTOR_RETRIEVAL,
            )
        return self._vector_store

    def embed_text(self, text: str) -> list[float]:
        """Trả về vector embedding của 1 đoạn text."""
        return get_embeddings().embed_query(text)

    def expand_by_relations(self, contract_id: int, numbers: list[str], relation_types: list[str]) -> list[dict]:
        """Trả về cạnh tới các Khoản liên quan tới numbers qua các loại quan hệ chéo trong relation_types.

        Không phân biệt chiều quan hệ - xem GET_RELATED_CLAUSE_NUMBERS.

        Args:
            contract_id: ID hợp đồng.
            numbers: Danh sách số hiệu Khoản gốc.
            relation_types: Danh sách loại quan hệ cần traversal (vd "REFERS_TO").

        Returns:
            Danh sách cạnh {"number", "from", "relation"}. Rỗng nếu numbers hoặc relation_types rỗng.
        """
        if not numbers or not relation_types:
            return []
        rows = get_graph().query(
            GET_RELATED_CLAUSE_NUMBERS,
            params={"contract_id": contract_id, "numbers": sorted(set(numbers)), "relation_types": relation_types},
        )
        return [
            {"number": r["number"], "from": r["from_number"], "to": r["to_number"], "relation": r["relation_type"]}
            for r in rows
        ]

    def expand_by_appendix_refs(self, contract_id: int, numbers: list[str]) -> list[dict]:
        """Trả về cạnh tới Clause Phụ lục được tham chiếu (quan hệ REFERS_TO_APPENDIX) từ numbers.

        Chạy KHÔNG ĐIỀU KIỆN (không qua classify_relevant_relations như expand_by_relations), giống
        expand_by_definitions - vì đích đã là 1 Clause NHỎ (node gốc hoặc đúng 1 mục con cụ thể của
        Phụ lục, xem llm/prompts/contract_graph_extraction_prompt.txt mục "THAM CHIẾU TỚI PHỤ LỤC"),
        không phải cả khối Phụ lục dài như trước khi tách sub-clause - nên không cần điều kiện hoá để
        tránh loãng ngữ cảnh, một khi Điều đã tham chiếu Phụ lục thì nội dung đó luôn cần thiết.

        Args:
            contract_id: ID hợp đồng.
            numbers: Danh sách số hiệu Khoản gốc.

        Returns:
            Danh sách cạnh {"number", "from", "relation"}. Rỗng nếu numbers rỗng.
        """
        if not numbers:
            return []
        rows = get_graph().query(
            GET_RELATED_CLAUSE_NUMBERS,
            params={
                "contract_id": contract_id,
                "numbers": sorted(set(numbers)),
                "relation_types": ["REFERS_TO_APPENDIX"],
            },
        )
        return [
            {"number": r["number"], "from": r["from_number"], "to": r["to_number"], "relation": r["relation_type"]}
            for r in rows
        ]

    def expand_by_definitions(self, contract_id: int, numbers: list[str]) -> list[dict]:
        """Trả về cạnh tới các Khoản định nghĩa các thuật ngữ mà numbers có sử dụng.

        Quan hệ USES_TERM -> Definition <- DEFINES. Không cần phân loại theo câu hỏi như
        expand_by_relations vì đây luôn là ngữ cảnh cần thiết để hiểu đúng thuật ngữ, không phụ thuộc
        loại câu hỏi.

        Args:
            contract_id: ID hợp đồng.
            numbers: Danh sách số hiệu Khoản gốc.

        Returns:
            Danh sách cạnh {"number", "from", "relation"} với relation="DEFINES". Rỗng nếu numbers rỗng.
        """
        if not numbers:
            return []
        rows = get_graph().query(
            GET_CLAUSES_DEFINING_USED_TERMS, params={"contract_id": contract_id, "numbers": sorted(set(numbers))}
        )
        return [
            {"number": r["number"], "from": r["from_number"], "to": r["number"], "relation": "DEFINES"}
            for r in rows
        ]

    def delete_contract(self, contract_id: int) -> None:
        """Xoá riêng 1 hợp đồng (mọi node mang agreement_id = contract_id, kể cả Agreement).

        Không ảnh hưởng các hợp đồng khác vì mọi node đều được scope theo agreement_id.

        Args:
            contract_id: Số hiệu hợp đồng cần xoá.
        """
        logger.info("Bắt đầu xoá graph của hợp đồng, contract_id=%s", contract_id)
        get_graph().query(DELETE_CONTRACT, params={"contract_id": contract_id})
        logger.info("Hoàn tất xoá graph của hợp đồng, contract_id=%s", contract_id)

    def next_contract_id(self) -> int:
        """Sinh số hiệu hợp đồng mới, tăng dần - dùng khi import 1 hợp đồng mới (không ghi đè hợp
        đồng cũ).

        Returns:
            Số hiệu hợp đồng kế tiếp.
        """
        records = get_graph().query(NEXT_CONTRACT_ID)
        return records[0]["next_id"]

    def build_graph(
        self,
        contract_id: int,
        contract_name: str,
        sections: list[dict],
        clauses: list[dict],
        extraction: ContractGraphExtraction,
        extraction_usage: dict,
        source_filename: str = "",
    ) -> int:
        """Tạo toàn bộ graph tri thức cho 1 hợp đồng trong Neo4j (Agreement, Section, Clause,
        Excerpt, Definition, quan hệ chéo, embedding) theo đúng thứ tự phụ thuộc.

        Args:
            contract_id: Số hiệu hợp đồng (do next_contract_id() cấp).
            contract_name: Tên hiển thị của hợp đồng (đã bỏ đuôi file).
            sections: Danh sách Section, xem ingestion.section_splitter.split_into_sections_and_clauses.
            clauses: Danh sách Clause, xem ingestion.section_splitter.split_into_sections_and_clauses.
            extraction: Kết quả trích xuất quan hệ/định nghĩa/bên tham gia bằng LLM.
            extraction_usage: usage_info của lệnh LLM trích xuất quan hệ (từ Graph.
                extract_relations) - gộp với chi phí embedding (tính trong method này) rồi lưu tổng vào
                Agreement node (SET_AGREEMENT_BUILD_COST), xem llm/usage.py.
            source_filename: Tên file gốc KÈM ĐUÔI (vd "hop_dong.pdf") - lưu riêng vì contract_name
                là tên hiển thị (đã bỏ đuôi file) nên không đủ để UI suy ra định dạng file khi tải
                lại trang.

        Returns:
            Số quan hệ chéo (REFERS_TO/DEPENDS_ON/EXCEPTION_TO) đã tạo.
        """
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
            is_appendix = c.get("is_appendix", False)
            default_type = "Thông tin chung và các bên tham gia hợp đồng" if is_preamble else "Khác"
            clause_rows.append(
                {
                    "number": c["number"],
                    "title": c["title"],
                    "text": c["text"],
                    "section_number": clause_number_to_section.get(c["number"], sections[0]["number"]),
                    "clause_type": rel.clause_type if rel else default_type,
                    "is_preamble": is_preamble,
                    "is_appendix": is_appendix,
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
        # tạo quan hệ cho thuật ngữ THẬT ĐÃ được định nghĩa trong hợp đồng (đã lọc ở extract_relations()).
        uses_term_rows = [
            {"clause_number": r.clause_number, "term": term} for r in extraction.clauses for term in r.uses_terms
        ]
        if uses_term_rows:
            graph.query(CREATE_CLAUSE_USES_TERM, params={"contract_id": contract_id, "uses": uses_term_rows})

        excerpt_rows = []
        excerpt_split_usages = []
        for c in clause_rows:
            excerpts, split_usage = split_clause_into_excerpts_llm(c["text"])
            if split_usage:
                excerpt_split_usages.append(split_usage)
            for chunk_index, excerpt_text in enumerate(excerpts):
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
            for target in r.appendix_refs:
                cross_relations.append({"from": r.clause_number, "to": target, "type": "REFERS_TO_APPENDIX"})

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
        build_usage = sum_usage(extraction_usage, embedding_usage, *excerpt_split_usages)
        graph.query(SET_AGREEMENT_BUILD_COST, params={"contract_id": contract_id, **build_usage})

        logger.info(
            "Hoàn tất tạo graph hợp đồng, contract_id=%s, n_clauses=%d, n_excerpts=%d, n_cross_relations=%d, "
            "n_definitions=%d, n_uses_term=%d, build_usage=%s",
            contract_id, len(clause_rows), len(excerpt_rows), len(cross_relations), len(definition_rows),
            len(uses_term_rows), build_usage,
        )

        return len(cross_relations)

    def export_contract_graph(self, contract_id: int) -> dict:
        """Đọc thẳng Neo4j, dựng danh sách node/edge phẳng cho toàn bộ 1 hợp đồng.

        Dùng cho trang "Full Graph" frontend (xem api/routes/contracts.py::get_contract_graph).
        KHÔNG gồm Excerpt/Definition/ClauseType (quá nhiều node vụn cho 1 cái nhìn tổng quan cả hợp
        đồng - xem GraphView.tsx phía frontend cho góc nhìn CHI TIẾT theo từng câu hỏi retrieval,
        vốn đã hiện tới cấp Excerpt).

        Khác scripts/build_contract_graph_export.py (chỉ xuất Clause + quan hệ chéo, dùng cho CLI
        debug graph.html cũ) - method này còn thêm tầng Section/Party/GoverningLaw/DisputeResolution
        để hiện ĐÚNG cấu trúc chứa (containment) thật trong Neo4j, không suy diễn từ số hiệu.

        Args:
            contract_id: Số hiệu hợp đồng cần xuất.

        Returns:
            dict {"contract_id", "contract_name", "nodes": [{"id","type","label",...}],
            "edges": [{"source","target","relation"}]}. "nodes"/"edges" rỗng nếu không tìm thấy
            hợp đồng (contract_name cũng rỗng - caller tự phân biệt "không tồn tại" theo đó).
        """
        graph = get_graph()

        agreement_rows = graph.query("MATCH (a:Agreement {contract_id: $id}) RETURN a.name AS name", params={"id": contract_id})
        if not agreement_rows:
            return {"contract_id": contract_id, "contract_name": "", "nodes": [], "edges": []}
        contract_name = agreement_rows[0]["name"]

        nodes: list[dict] = [{"id": "agreement", "type": "Contract", "label": contract_name}]
        edges: list[dict] = []

        section_rows = graph.query(
            "MATCH (:Agreement {contract_id: $id})-[:HAS_SECTION]->(s:Section) RETURN s.number AS number, s.title AS title",
            params={"id": contract_id},
        )
        for s in section_rows:
            node_id = f"section:{s['number']}"
            nodes.append({"id": node_id, "type": "Section", "label": s["title"] or s["number"], "number": s["number"]})
            edges.append({"source": "agreement", "target": node_id, "relation": "HAS_SECTION"})

        clause_rows = graph.query(
            """
            MATCH (sec:Section {agreement_id: $id})-[:HAS_CLAUSE]->(c:Clause)
            WHERE coalesce(c.is_preamble, false) = false
            RETURN c.number AS number, c.title AS title, c.text AS text, coalesce(c.is_appendix, false) AS is_appendix,
                   sec.number AS section_number
            ORDER BY c.number
            """,
            params={"id": contract_id},
        )
        for c in clause_rows:
            node_id = f"clause:{c['number']}"
            node_type = "Appendix" if c["is_appendix"] else "Clause"
            # Khoản không có tiêu đề riêng (thường gặp ở Khoản liệt kê điều kiện) - lấy 1 đoạn nội dung
            # đầu làm nhãn thay vì chỉ hiện trơ trụi số hiệu, để phân biệt được các node cùng cấp trên graph.
            label = c["title"] or (snippet(c["text"]) if c["text"] else c["number"])
            nodes.append({"id": node_id, "type": node_type, "label": label, "number": c["number"]})
            edges.append({"source": f"section:{c['section_number']}", "target": node_id, "relation": "HAS_CLAUSE"})

        party_rows = graph.query(
            "MATCH (:Agreement {contract_id: $id})-[hp:HAS_PARTY]->(p:Organization) RETURN p.name AS name, hp.role AS role",
            params={"id": contract_id},
        )
        for p in party_rows:
            node_id = f"party:{p['name']}"
            nodes.append({"id": node_id, "type": "Party", "label": p["name"], "role": p.get("role") or ""})
            edges.append({"source": "agreement", "target": node_id, "relation": "HAS_PARTY"})

        gl_rows = graph.query(
            "MATCH (:Agreement {contract_id: $id})-[:GOVERNED_BY]->(gl:GoverningLaw) RETURN gl.country AS country, gl.state AS state",
            params={"id": contract_id},
        )
        for gl in gl_rows:
            label = gl.get("country") or "Luật áp dụng"
            nodes.append({"id": "governing_law", "type": "GoverningLaw", "label": label})
            edges.append({"source": "agreement", "target": "governing_law", "relation": "GOVERNED_BY"})

        dr_rows = graph.query(
            "MATCH (:Agreement {contract_id: $id})-[:HAS_DISPUTE_RULE]->(dr:DisputeResolution) RETURN dr.method AS method, dr.venue AS venue",
            params={"id": contract_id},
        )
        for dr in dr_rows:
            nodes.append({"id": "dispute_resolution", "type": "DisputeResolution", "label": dr.get("method") or "Giải quyết tranh chấp"})
            edges.append({"source": "agreement", "target": "dispute_resolution", "relation": "HAS_DISPUTE_RULE"})

        cross_rows = graph.query(
            """
            MATCH (a:Clause {agreement_id: $id})-[r]-(b:Clause {agreement_id: $id})
            WHERE type(r) IN $rel_types
            RETURN DISTINCT startNode(r).number AS from_number, endNode(r).number AS to_number, type(r) AS relation
            """,
            params={"id": contract_id, "rel_types": _CROSS_RELATION_TYPES},
        )
        for r in cross_rows:
            edges.append({"source": f"clause:{r['from_number']}", "target": f"clause:{r['to_number']}", "relation": r["relation"]})

        defines_rows = graph.query(
            "MATCH (c:Clause {agreement_id:$id})-[:USES_TERM]->(d:Definition)<-[:DEFINES]-(src:Clause) "
            "RETURN DISTINCT src.number AS from_number, c.number AS to_number",
            params={"id": contract_id},
        )
        for r in defines_rows:
            edges.append({"source": f"clause:{r['from_number']}", "target": f"clause:{r['to_number']}", "relation": "DEFINES"})

        return {"contract_id": contract_id, "contract_name": contract_name, "nodes": nodes, "edges": edges}

    def extract_relations(self, contract_name: str, clauses: list[dict]) -> tuple[ContractGraphExtraction, dict]:
        """Gọi LLM trích xuất toàn bộ quan hệ pháp lý của 1 hợp đồng, rồi lọc và log để review.

        Đây là bước LLM đắt nhất trong pipeline import hợp đồng (services/contract_service.py::
        ContractService.import_contract) - gọi 1 lần cho TOÀN BỘ hợp đồng. Kết quả thô từ LLM luôn
        được lọc qua _drop_invalid_references/_drop_invalid_uses_terms trước khi trả về, vì LLM có
        thể "ảo giác" tham chiếu tới số Điều/thuật ngữ không tồn tại trong văn bản gốc.

        usage_info giờ được track thật (trước đây method này gọi thẳng structured_model.invoke()
        không qua invoke_structured_with_usage() nên KHÔNG có thông tin chi phí, dù đây là lệnh LLM
        đắt nhất trong pipeline - cả hợp đồng trong 1 lần gọi).

        Args:
            contract_name: Tên hợp đồng, dùng để đưa vào prompt và log.
            clauses: Danh sách dict mô tả từng Điều/Khoản/Phụ lục (xem _clause_label).

        Returns:
            Tuple (extraction, usage_info) - extraction là ContractGraphExtraction đã lọc quan
            hệ ảo giác, usage_info gồm input_tokens/output_tokens/cost_usd.
        """
        clauses_block = "\n\n".join(f"{clause_label(c)}\n{c['text']}" for c in clauses)
        user_content = f"Hợp đồng '{contract_name}', danh sách các Điều:\n\n{clauses_block}"

        logger.info("Gọi LLM trích xuất quan hệ hợp đồng '%s', n_clauses=%d, input_len=%d", contract_name, len(clauses), len(user_content))
        extraction, usage = invoke_structured_with_usage(
            GRAPH_EXTRACTION_MODEL, _EXTRACTION_SYSTEM_PROMPT, user_content, ContractGraphExtraction
        )

        migrate_appendix_refs(extraction)
        valid_numbers = {c["number"] for c in clauses}
        drop_invalid_references(extraction, valid_numbers)
        drop_invalid_uses_terms(extraction)
        log_relations_for_review(extraction)
        logger.info(
            "Hoàn tất trích xuất quan hệ hợp đồng '%s', n_clause_relations=%d, usage=%s",
            contract_name, len(extraction.clauses), usage,
        )
        return extraction, usage
