"""Truy hồi các Điều khoản liên quan nhất tới 1 mục checklist bằng vector search (langchain_neo4j).

Luồng retrieve_relevant_clauses() gồm 5 bước tách bạch, mỗi bước là 1 hàm riêng để sau này dễ
thay/thêm chiến lược mới (vd đổi expand_to_full_article() sang graph traversal) mà không đụng
các bước còn lại:
1. Vector search trên Excerpt cho TỪNG query riêng (question/pass_criteria/violation_criteria,
   không gộp chung 1 chuỗi) -> điểm số theo từng Clause (_search_matching_clauses)
2. Mở rộng tập Clause - luôn kéo theo cả Điều cha, kéo theo Khoản liên quan qua quan hệ chéo
   (REFERS_TO/DEPENDS_ON/EXCEPTION_TO) khi câu hỏi có từ khoá gợi ý loại quan hệ đó, và luôn kéo
   theo Khoản định nghĩa thuật ngữ mà Khoản đã khớp có sử dụng (USES_TERM/DEFINES) - xem
   rag/retrieval/expansion.py
3. Lấy metadata + toàn bộ Excerpt cho tập Clause cuối cùng (_load_clause_details)
4. Lắp preamble + metadata hợp đồng (luật áp dụng, giải quyết tranh chấp) vào đầu danh sách - luôn
   có, không qua vector search
5. Gộp các Clause (Khoản) về theo Điều cha (_group_by_article) - kết quả trả về là danh sách
   Điều, mỗi Điều chứa các Khoản của nó, không phải danh sách Khoản phẳng như trước.

Câu lệnh Cypher nằm trong knowledge_graph/queries.py."""

from __future__ import annotations

import logging

from langchain_neo4j import Neo4jVector

from config.settings import (
    MIN_RETRIEVAL_SCORE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    SCORE_GAP_MARGIN,
    TOP_K_CEILING_PER_QUERY,
)
from knowledge_graph.client import get_graph
from knowledge_graph.queries import GET_AGREEMENT_METADATA, GET_CLAUSE_EXCERPTS, GET_CLAUSES_INFO, GET_PREAMBLE_CLAUSE, VECTOR_RETRIEVAL
from llm.embeddings import get_embeddings
from rag.retrieval.expansion import classify_relevant_relations, expand_by_definitions, expand_by_relations, expand_to_full_article

logger = logging.getLogger(__name__)

_vector_store: Neo4jVector | None = None

_OVERFETCH_FACTOR = 3  # 1 Clause dài có thể có nhiều Excerpt cùng lọt top match - lấy dư ứng
# viên rồi dedupe theo Clause (giữ điểm cao nhất) để không mất chỗ của các Clause khác biệt.


def get_vector_store() -> Neo4jVector:
    global _vector_store
    if _vector_store is None:
        get_graph()  # garante driver/index đã sẵn sàng (index tạo trong knowledge_graph/builder.py)
        _vector_store = Neo4jVector.from_existing_index(
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
    return _vector_store


def embed_text(text: str) -> list[float]:
    return get_embeddings().embed_query(text)


class _MatchResult:
    """Kết quả bước 1 (vector search) - tách riêng khỏi dict để rõ field, tránh KeyError âm
    thầm khi thêm/bớt field sau này."""

    def __init__(self) -> None:
        self.best_score_by_number: dict[str, float] = {}
        self.article_number_by_number: dict[str, str] = {}
        self.matched_score_by_chunk: dict[tuple[str, int], float] = {}
        self.selected_numbers: set[str] = set()


def _select_query_candidates(
    query_best_by_number: dict[str, float],
    article_number_by_number: dict[str, str],
    min_score: float,
    gap_margin: float,
    top_k_ceiling: int,
) -> list[str]:
    """Chọn Clause nào giữ lại cho 1 truy vấn - ADAPTIVE theo ĐỘ MẠNH và ĐỘ ĐA DẠNG của chính kết
    quả truy vấn đó, thay vì luôn lấy đúng K Clause cố định bất kể phân bố điểm:

    - Luôn giữ ứng viên hạng 1 (nếu đạt 'min_score' - sàn tuyệt đối như cũ).
    - Ứng viên hạng 2 trở đi CHỈ giữ thêm khi ĐỦ CẢ 2 điều kiện:
      (a) ĐỘ MẠNH: điểm của nó phải đủ GẦN điểm hạng 1 (trong khoảng 'gap_margin') - chỉ ứng viên
          thực sự cạnh tranh với hạng 1 mới đáng tin, không phải một ứng viên đuối hơn hẳn nhưng
          tình cờ vẫn qua được ngưỡng sàn.
      (b) ĐỘ ĐA DẠNG: nó phải thuộc 1 Điều KHÁC với các ứng viên đã chọn trước đó của truy vấn này -
          vì expand_to_full_article() (xem rag/retrieval/expansion.py) đã tự kéo theo TOÀN BỘ Khoản
          cùng Điều với ứng viên đã chọn, nên 1 ứng viên khác cùng Điều là dư thừa (không thêm
          phạm vi thông tin mới), trong khi ứng viên thuộc Điều khác mới thực sự mở rộng phạm vi.
    Nhờ vậy truy vấn có 1 đáp án rõ ràng tự nhiên chỉ giữ 1 Clause (không thêm nhiễu), còn truy vấn
    cần bằng chứng từ nhiều Điều khác nhau tự nhiên giữ thêm Clause của Điều đó nếu điểm đủ gần
    nhau - không cần đoán trước 1 con số K cố định phù hợp cho mọi truy vấn.

    'top_k_ceiling' là trần AN TOÀN (chống trường hợp hiếm nhiều Điều cùng đạt điểm rất gần nhau
    khiến ngữ cảnh phình không kiểm soát), không phải số lượng mặc định sẽ luôn lấy đủ."""
    candidates = sorted(query_best_by_number, key=lambda n: query_best_by_number[n], reverse=True)
    if not candidates:
        return []

    above_floor = [n for n in candidates if query_best_by_number[n] >= min_score]
    if not above_floor:
        return candidates[:1]  # không ứng viên nào đạt sàn - vẫn giữ 1 ứng viên tốt nhất để
        # khái niệm của query này không bị bỏ trắng hoàn toàn.

    top_score = query_best_by_number[above_floor[0]]
    selected: list[str] = [above_floor[0]]
    selected_articles = {article_number_by_number[above_floor[0]]}
    for number in above_floor[1:]:
        if len(selected) >= top_k_ceiling:
            break
        if query_best_by_number[number] < top_score - gap_margin:
            break  # đã sắp giảm dần theo điểm - qua ngưỡng này thì các ứng viên sau càng yếu hơn
        article = article_number_by_number[number]
        if article in selected_articles:
            continue  # cùng Điều với ứng viên đã chọn - dư thừa, expand_to_full_article() đã lo
        selected.append(number)
        selected_articles.add(article)
    return selected


def _search_matching_clauses(
    contract_id: int,
    query_texts: list[str],
    min_score: float = MIN_RETRIEVAL_SCORE,
    gap_margin: float = SCORE_GAP_MARGIN,
    top_k_ceiling: int = TOP_K_CEILING_PER_QUERY,
) -> _MatchResult:
    """Bước 1: vector search trên Excerpt cho TỪNG query trong 'query_texts' riêng biệt (không
    gộp thành 1 chuỗi rồi embed chung - question/pass_criteria/violation_criteria thường chứa
    từ khoá/con số rất cụ thể, gộp chung sẽ pha loãng tín hiệu của từng cái).

    Việc CHỌN Clause nào được giữ lại cũng làm NGAY TRONG TỪNG query (xem _select_query_candidates -
    adaptive theo độ mạnh/đa dạng của chính truy vấn đó), rồi HỢP (union, khử trùng lặp theo number)
    kết quả chọn của tất cả query - KHÔNG gộp điểm mọi query vào 1 pool chung rồi lấy top-K toàn
    cục. Lý do: 1 mục checklist có thể tách ra rất nhiều truy vấn (nhiều khái niệm khác nhau); nếu
    xếp hạng chung, khái niệm có điểm nhỉnh hơn (thường là câu hỏi phổ biến) sẽ chiếm hết chỗ của
    khái niệm khác dù khái niệm đó vẫn có Clause đúng với điểm số hợp lệ - mỗi truy vấn cần được
    đảm bảo có 'suất' riêng để khái niệm nào cũng có cơ hội tìm ra đúng Điều khoản của nó."""
    query_texts = [q for q in query_texts if q and q.strip()]
    if not query_texts:
        return _MatchResult()

    # Embed cả batch trong 1 lần gọi API (embed_texts nhận list) - không tốn thêm request so
    # với gộp 1 chuỗi, chỉ tốn thêm vòng lặp truy vấn Neo4j (rẻ) cho mỗi vector.
    vectors = get_embeddings().embed_texts(query_texts)

    match = _MatchResult()
    store = get_vector_store()
    for text, vector in zip(query_texts, vectors):
        results = store.similarity_search_with_score_by_vector(
            vector,
            k=top_k_ceiling * _OVERFETCH_FACTOR,
            filter={"agreement_id": contract_id, "is_preamble": False},
            query=text,  # langchain_neo4j luôn cần "query" (text gốc) dù đã truyền sẵn vector,
            # dùng nội bộ cho nhánh search_type="hybrid" (không dùng ở đây vì mặc định "vector").
        )
        query_best_by_number: dict[str, float] = {}
        for doc, score in results:
            number = doc.metadata["number"]
            chunk_index = doc.metadata["chunk_index"]
            match.article_number_by_number[number] = doc.metadata["article_number"]
            key = (number, chunk_index)
            if key not in match.matched_score_by_chunk or score > match.matched_score_by_chunk[key]:
                match.matched_score_by_chunk[key] = round(score, 4)
            if number not in match.best_score_by_number or score > match.best_score_by_number[number]:
                match.best_score_by_number[number] = score
            if number not in query_best_by_number or score > query_best_by_number[number]:
                query_best_by_number[number] = score

        selected = _select_query_candidates(
            query_best_by_number, match.article_number_by_number, min_score, gap_margin, top_k_ceiling
        )
        match.selected_numbers.update(selected)
    return match


def _make_clause_dict(number: str, title: str, article_number: str, article_title: str, score: float | None, excerpts: list[dict]) -> dict:
    """Cấu trúc 1 Clause trả về cho phần gọi ngoài (checklist_evaluation.py, frontend Evidence) -
    dùng CHUNG cho mọi nguồn dựng Clause (đã khớp vector search, kéo thêm theo Điều, hay
    preamble) để không lặp lại cùng 1 cấu trúc dict ở nhiều nơi (từng là bug tiềm ẩn: thêm field
    mới phải nhớ sửa đủ mọi chỗ dựng dict thủ công)."""
    return {
        "number": number,
        "title": title,
        "article_number": article_number,
        "article_title": article_title,
        "score": round(score, 4) if score is not None else None,
        "text": "\n\n".join(e["text"] for e in excerpts),
        "excerpts": excerpts,
    }


def _load_clause_details(contract_id: int, numbers: list[str], match: _MatchResult) -> list[dict]:
    """Bước 3: lấy title/article_number/article_title + toàn bộ Excerpt cho từng Clause trong
    'numbers' - áp dụng cho CẢ Clause đã khớp vector search LẪN Clause được kéo thêm ở bước 2
    (Clause kéo thêm không có trong metadata vector search nên phải tra riêng qua Cypher)."""
    if not numbers:
        return []

    info_rows = get_graph().query(GET_CLAUSES_INFO, params={"contract_id": contract_id, "numbers": numbers})
    info_by_number = {r["number"]: r for r in info_rows}

    excerpt_rows = get_graph().query(GET_CLAUSE_EXCERPTS, params={"contract_id": contract_id, "numbers": numbers})
    excerpts_by_number: dict[str, list[dict]] = {}
    for r in excerpt_rows:
        excerpts_by_number.setdefault(r["number"], []).append(r)
    for lst in excerpts_by_number.values():
        lst.sort(key=lambda r: r["chunk_index"])

    clauses = []
    for number in numbers:
        info = info_by_number.get(number)
        if info is None:
            continue
        excerpts = [
            {
                "chunk_index": r["chunk_index"],
                "text": r["text"],
                "score": match.matched_score_by_chunk.get((number, r["chunk_index"])),
            }
            for r in excerpts_by_number.get(number, [])
        ]
        clauses.append(
            _make_clause_dict(
                number,
                info["title"],
                info["article_number"],
                info["article_title"],
                match.best_score_by_number.get(number),
                excerpts,
            )
        )
    return clauses


def _sort_key(match: _MatchResult):
    """Clause đã khớp vector search xếp trước (điểm cao trước), Clause chỉ được kéo thêm theo
    Điều (không có điểm) xếp sau cùng, theo đúng thứ tự số hiệu."""

    def key(number: str):
        score = match.best_score_by_number.get(number)
        return (0, -score) if score is not None else (1, number)

    return key


def _select_top_numbers(match: _MatchResult) -> list[str]:
    """Trả về các Clause đã được CHỌN (mỗi query tự chọn top của nó trong _search_matching_clauses,
    hàm này chỉ sắp xếp lại theo điểm cao nhất từng Clause đạt được, để phần hiển thị/log ổn định)."""
    return sorted(match.selected_numbers, key=lambda n: match.best_score_by_number.get(n, 0.0), reverse=True)


def _clause_sort_key(number: str) -> list[int]:
    if number == "0":
        return [-1]
    try:
        return [int(p) for p in number.split(".")]
    except ValueError:
        return [10**9]  # số hiệu bất thường (không thuần số) - đẩy xuống cuối, không raise


def _group_by_article(clauses: list[dict]) -> list[dict]:
    """Gộp danh sách Clause (Khoản) phẳng về theo Điều cha - thứ tự Điều giữ theo lần xuất hiện
    ĐẦU TIÊN trong 'clauses' (đã sắp matched-trước ở retrieve_relevant_clauses), thứ tự Khoản
    trong từng Điều luôn tăng dần theo số hiệu bất kể thứ hạng match."""
    order: list[str] = []
    groups: dict[str, dict] = {}
    for c in clauses:
        art = c["article_number"]
        if art not in groups:
            groups[art] = {"article_number": art, "article_title": c["article_title"], "score": None, "clauses": []}
            order.append(art)
        groups[art]["clauses"].append(c)
        if c["score"] is not None and (groups[art]["score"] is None or c["score"] > groups[art]["score"]):
            groups[art]["score"] = c["score"]

    result = []
    for art in order:
        g = groups[art]
        g["clauses"].sort(key=lambda c: _clause_sort_key(c["number"]))
        header = f"Điều {g['article_number']}. {g['article_title']}" if g["article_title"] else f"Điều {g['article_number']}"
        g["text"] = header + "\n\n" + "\n\n".join(c["text"] for c in g["clauses"])
        result.append(g)
    return result


def _build_metadata_group(contract_id: int) -> dict | None:
    """Điều 'ảo' đính kèm luật áp dụng + phương thức giải quyết tranh chấp - tra cứu trực tiếp
    theo contract_id (GoverningLaw/DisputeResolution), KHÔNG qua vector search vì đây là fact cố
    định của cả hợp đồng, không phải nội dung cần so khớp độ liên quan. Trả None nếu hợp đồng
    không có dữ liệu này (LLM extraction không trích được, vd hợp đồng không ghi rõ)."""
    rows = get_graph().query(GET_AGREEMENT_METADATA, params={"contract_id": contract_id})
    if not rows:
        return None
    r = rows[0]
    lines = []
    if r.get("governing_law_country"):
        law = r["governing_law_country"]
        if r.get("governing_law_state"):
            law += f", {r['governing_law_state']}"
        lines.append(f"Luật áp dụng: {law}")
    if r.get("dispute_method"):
        dispute = r["dispute_method"]
        if r.get("dispute_venue"):
            dispute += f" tại {r['dispute_venue']}"
        lines.append(f"Phương thức giải quyết tranh chấp: {dispute}")
    if not lines:
        return None
    text = "\n".join(lines)
    excerpts = [{"chunk_index": 0, "text": text, "score": None}]
    clause = _make_clause_dict("meta", "Luật áp dụng & giải quyết tranh chấp", "meta", "Luật áp dụng & giải quyết tranh chấp", None, excerpts)
    return {
        "article_number": "meta", "article_title": "Luật áp dụng & giải quyết tranh chấp", "score": None,
        "clauses": [clause], "text": text,
    }


def retrieve_relevant_clauses(
    contract_id: int,
    query_texts: list[str],
    min_score: float = MIN_RETRIEVAL_SCORE,
    gap_margin: float = SCORE_GAP_MARGIN,
    top_k_ceiling: int = TOP_K_CEILING_PER_QUERY,
) -> list[dict]:
    """query_texts: danh sách truy vấn ĐÃ SẴN SÀNG để search (mỗi phần tử embed riêng, xem
    _search_matching_clauses) - việc DỰNG danh sách này (từ question/pass_criteria/violation_criteria
    thô, hay từ LLM phân rã thành nhiều truy vấn con) là trách nhiệm của tầng gọi (xem
    rag/checklist_graph.py::_node_generate_queries), không phải của hàm này."""
    match = _search_matching_clauses(contract_id, query_texts, min_score, gap_margin, top_k_ceiling)
    top_numbers = _select_top_numbers(match)

    numbers_to_load = list(top_numbers)
    matched_articles = [match.article_number_by_number[n] for n in top_numbers]
    for n in expand_to_full_article(contract_id, matched_articles):
        if n not in numbers_to_load:
            numbers_to_load.append(n)

    # Query-aware: chỉ kéo thêm Khoản liên quan qua quan hệ chéo (REFERS_TO/DEPENDS_ON/
    # EXCEPTION_TO) khi câu hỏi có từ khoá gợi ý loại quan hệ đó - tránh kéo mù mọi quan hệ không
    # liên quan tới câu hỏi (xem rag/retrieval/expansion.py::classify_relevant_relations).
    relevant_relations = classify_relevant_relations(query_texts)
    for n in expand_by_relations(contract_id, top_numbers, relevant_relations):
        if n not in numbers_to_load:
            numbers_to_load.append(n)

    # Kéo theo Khoản định nghĩa các thuật ngữ mà Khoản đã khớp có SỬ DỤNG (USES_TERM) - luôn chạy,
    # không cần phân loại theo câu hỏi vì hiểu đúng thuật ngữ luôn cần thiết bất kể loại câu hỏi.
    for n in expand_by_definitions(contract_id, top_numbers):
        if n not in numbers_to_load:
            numbers_to_load.append(n)

    clauses = _load_clause_details(contract_id, numbers_to_load, match)
    clauses.sort(key=lambda c: _sort_key(match)(c["number"]))

    preamble_records = get_graph().query(GET_PREAMBLE_CLAUSE, params={"contract_id": contract_id})
    if preamble_records:
        p0 = preamble_records[0]
        preamble_excerpts = [{"chunk_index": r["chunk_index"], "text": r["text"], "score": None} for r in preamble_records]
        clauses.insert(
            0, _make_clause_dict(p0["number"], p0["title"], p0["article_number"], p0["article_title"], None, preamble_excerpts)
        )
    else:
        logger.warning("Không tìm thấy clause preamble cho contract_id=%s", contract_id)

    groups = _group_by_article(clauses)

    metadata_group = _build_metadata_group(contract_id)
    if metadata_group:
        groups.insert(0, metadata_group)

    logger.info(
        "Truy hồi clause cho contract_id=%s: gap_margin=%.2f, top_k_ceiling=%d, min_score=%.2f, "
        "n_queries=%d, n_matched=%d, n_clauses=%d, n_articles=%d",
        contract_id, gap_margin, top_k_ceiling, min_score, len(query_texts), len(top_numbers), len(clauses), len(groups),
    )

    return groups
