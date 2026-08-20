"""4 bước của pipeline retrieval, gộp thành 1 class Retrieval - retrieve (vector search thô)
-> rerank (chấm lại điểm + áp ngưỡng) -> expand (mở rộng qua quan hệ đồ thị) -> build_context (lắp
Clause cuối cùng). Mỗi method là THUẦN theo state truyền vào/trả ra (dict/list, không tự giữ state
giữa các lần gọi ngoài config truyền ở __init__) - dùng CHUNG bởi:
- checklist/nodes.py::run_{retrieve,rerank,expand,build_context} (mỗi node LangGraph tạo 1
  Retrieval rồi gọi đúng 1 method, đọc/ghi qua ChecklistItemState - KHÔNG giữ instance giữa
  các node vì mỗi node là 1 lần gọi độc lập trong LangGraph).
- run() ở cuối class, gọi nối tiếp cả 4 method bằng lời gọi thường, không qua LangGraph - cho nơi cần
  retrieval trực tiếp như ui/app.py hoặc scripts/benchmark_retrieval.py.

Tách thành method riêng THAY VÌ để logic bên trong node để tránh trùng lặp giữa 2 cách gọi trên."""

from __future__ import annotations

import logging

from config.settings import (
    MIN_RETRIEVAL_SCORE,
    RERANK_GAP_MARGIN,
    RERANK_MIN_SCORE,
    SCORE_GAP_MARGIN,
    TOP_K_CEILING_PER_QUERY,
    USE_RERANK,
)
from knowledge_graph.client import get_graph
from knowledge_graph.queries import FIND_SIMILAR_CLAUSES_CROSS_CONTRACT, GET_CLAUSE_TEXT_AND_TYPE
from knowledge_graph.graph import Graph
from llm.embeddings import get_embeddings
from rag.builder import ContextBuilder
from rag.reranker import get_reranker
from schema.retrieval import MatchState, RawCandidate

logger = logging.getLogger(__name__)

_SIMILAR_CLAUSES_OVERFETCH_FACTOR = 5  # 1 Clause có thể có nhiều Excerpt cùng lọt top match, và
# nhiều Excerpt của CÙNG 1 Clause tính là trùng sau dedupe - overfetch rộng hơn top_k để còn đủ
# Clause KHÁC NHAU sau khi dedupe, đặc biệt khi same_type_only=True thu hẹp thêm số ứng viên hợp lệ.


class ClauseNotFoundError(Exception):
    """Không tìm thấy Clause nguồn (contract_id, number) trong graph."""


class Retrieval:
    """Truy hồi Clause cho 1 contract, cấu hình 1 lần ở __init__, gọi các method theo thứ tự retrieve
    -> rerank -> expand -> build_context (hoặc run() để chạy nối tiếp cả 4)."""

    _ALL_RELATION_TYPES = ["REFERS_TO", "DEPENDS_ON", "EXCEPTION_TO"]
    _OVERFETCH_FACTOR = 3  # 1 Clause dài có thể có nhiều Excerpt cùng lọt top match - lấy dư ứng
    # viên rồi dedupe theo Clause (giữ điểm cao nhất) để không mất chỗ của các Clause khác biệt.

    def __init__(
        self,
        contract_id: int,
        min_score: float = MIN_RETRIEVAL_SCORE,
        gap_margin: float = SCORE_GAP_MARGIN,
        top_k_ceiling: int = TOP_K_CEILING_PER_QUERY,
        use_rerank: bool = USE_RERANK,
    ) -> None:
        self.contract_id = contract_id
        self.min_score = min_score
        self.gap_margin = gap_margin
        self.top_k_ceiling = top_k_ceiling
        self.use_rerank = use_rerank
        self._graph = Graph()
        self._context_builder = ContextBuilder()

    def retrieve(self, query_texts: list[str]) -> dict[str, list[RawCandidate]]:
        """Bước 1: vector search trên Excerpt cho từng query trong query_texts riêng biệt, overfetch
        (chưa chọn lọc) - việc chọn ứng viên nào giữ lại chuyển hết sang rerank() (tách khỏi vector
        search để rerank() có thể chấm lại điểm TRƯỚC KHI chọn, xem docstring class).

        Không gộp query_texts thành 1 chuỗi rồi embed chung - question/pass_criteria/violation_criteria
        thường chứa từ khoá/con số rất cụ thể, gộp chung sẽ pha loãng tín hiệu của từng cái.
        """
        query_texts = [q for q in query_texts if q and q.strip()]
        if not query_texts:
            return {}

        # Embed cả batch trong 1 lần gọi API (embed_texts nhận list) - không tốn thêm request so với
        # gộp 1 chuỗi, chỉ tốn thêm vòng lặp truy vấn Neo4j (rẻ) cho mỗi vector.
        vectors = get_embeddings().embed_texts(query_texts)
        store = self._graph.get_vector_store()

        raw_candidates: dict[str, list[RawCandidate]] = {}
        for text, vector in zip(query_texts, vectors):
            results = store.similarity_search_with_score_by_vector(
                vector,
                k=self.top_k_ceiling * self._OVERFETCH_FACTOR,
                filter={"agreement_id": self.contract_id, "is_preamble": False},
                query=text,  # langchain_neo4j luôn cần "query" (text gốc) dù đã truyền sẵn vector,
                # dùng nội bộ cho nhánh search_type="hybrid" (không dùng ở đây vì mặc định "vector").
            )
            raw_candidates[text] = [
                {
                    "number": doc.metadata["number"],
                    "chunk_index": doc.metadata["chunk_index"],
                    "article_number": doc.metadata["article_number"],
                    "score": score,
                    "content": doc.page_content,
                }
                for doc, score in results
            ]
        return raw_candidates

    def rerank(self, raw_candidates: dict[str, list[RawCandidate]]) -> tuple[MatchState, list[str]]:
        """Bước 2: (tuỳ chọn) chấm lại điểm bằng cross-encoder model (xem rag/reranker.py)
        THAY VÌ dùng thẳng cosine similarity, rồi áp ngưỡng CHỌN Clause nào giữ lại cho từng truy vấn
        con - HỢP (union, khử trùng lặp theo number) kết quả chọn của tất cả query - KHÔNG gộp điểm
        mọi query vào 1 pool chung rồi lấy top-K toàn cục. Lý do: 1 mục checklist có thể tách ra rất
        nhiều truy vấn (nhiều khái niệm khác nhau); nếu xếp hạng chung, khái niệm có điểm nhỉnh hơn
        sẽ chiếm hết chỗ của khái niệm khác dù khái niệm đó vẫn có Clause đúng với điểm số hợp lệ.

        use_rerank=True: đổi luôn ngưỡng chọn sang thang điểm rerank (RERANK_MIN_SCORE/RERANK_GAP_MARGIN)
        vì 2 thang điểm không tương đương - dùng lẫn ngưỡng cosine cho điểm rerank sẽ chọn sai hoàn toàn.

        Returns:
            Tuple (match, top_numbers) - match tích luỹ điểm/Điều cha của MỌI Clause đã thấy (dùng
            lại ở build_context()), top_numbers là danh sách số hiệu Clause đã chọn, sắp theo điểm
            giảm dần.
        """
        match: MatchState = {"best_score_by_number": {}, "article_number_by_number": {}, "matched_score_by_chunk": {}}
        selected_numbers: set[str] = set()

        for text, candidates in raw_candidates.items():
            query_min_score, query_gap_margin = self.min_score, self.gap_margin
            if self.use_rerank and candidates:
                rerank_scores = get_reranker().score_pairs(text, [c["content"] for c in candidates])
                candidates = [{**c, "score": s} for c, s in zip(candidates, rerank_scores)]
                query_min_score, query_gap_margin = RERANK_MIN_SCORE, RERANK_GAP_MARGIN

            query_best_by_number: dict[str, float] = {}
            for c in candidates:
                number, chunk_index, score = c["number"], c["chunk_index"], c["score"]
                match["article_number_by_number"][number] = c["article_number"]
                self._context_builder.update_best_score(match["matched_score_by_chunk"], (number, chunk_index), round(score, 4))
                self._context_builder.update_best_score(match["best_score_by_number"], number, score)
                self._context_builder.update_best_score(query_best_by_number, number, score)

            selected = self._select_query_candidates(query_best_by_number, query_min_score, query_gap_margin)
            selected_numbers.update(selected)

        top_numbers = sorted(selected_numbers, key=lambda n: match["best_score_by_number"].get(n, 0.0), reverse=True)
        return match, top_numbers

    def expand(self, top_numbers: list[str], match: MatchState) -> tuple[list[dict], list[str]]:
        """Bước 3: mở rộng tập Clause - CHỈ theo quan hệ đồ thị THẬT (REFERS_TO/DEPENDS_ON/EXCEPTION_TO/
        REFERS_TO_APPENDIX, cả 2 chiều) và Khoản định nghĩa thuật ngữ mà Khoản đã khớp có sử dụng
        (USES_TERM/DEFINES) - KHÔNG tự động kéo mọi Khoản anh em cùng Điều - để evidences phản ánh
        đúng "cái nó thực sự nhận được", không dội thêm ngữ cảnh không liên quan.

        QUAN TRỌNG - vì sao GỘP SEED (mọi top_numbers từ mọi truy vấn) trước khi mở rộng đồ thị 1 LẦN
        (thay vì mở rộng riêng cho từng query rồi mới hợp) vẫn cho ra ĐÚNG NGUYÊN kết quả như làm
        tách biệt - về lý thuyết đồ thị, tập node "với được từ (A hợp B)" LUÔN bằng "(tập với được từ
        A) hợp (tập với được từ B)", dù gộp trước hay sau. Ví dụ: câu hỏi 1 khớp Khoản A, câu hỏi 2
        khớp Khoản B, đồ thị có quan hệ thật A -> C:

            Tách biệt từng câu rồi merge:
                Câu 1: search -> {A}  ->  tự mở rộng -> {A, C}
                Câu 2: search -> {B}  ->  tự mở rộng -> {B}
                Merge: {A, C} hợp {B} = {A, B, C}

            Gộp seed trước rồi mở rộng chung 1 lần (cách code đang làm):
                Frontier ban đầu = {A, B}  (gộp ngay từ đầu)
                Mở rộng 1 lần -> tìm được C (từ A -> C)
                Kết quả: {A, B, C}

        -> Ra CÙNG 1 kết quả {A, B, C} - gộp trước CHỈ nhanh hơn (đỡ query Neo4j lặp lại cho cùng
        loại quan hệ khi nhiều query cùng chạm 1 Khoản), không làm mất hay thừa Khoản nào so với tách
        biệt.

        Traversal CHẠY TRANSITIVE (bắc cầu) VÀ CẢ 2 CHIỀU: nếu A -> B -> C -> D là chuỗi quan hệ thật
        nối tiếp nhau, mỗi vòng lặp dùng CHÍNH các Khoản MỚI vừa tìm được ở vòng trước làm "frontier"
        để dò tiếp - không dừng ở 1-hop. KHÔNG giới hạn trần số vòng - lấy HẾT những gì graph thật sự
        nối tới được, chấp nhận đánh đổi precision thấp hơn để không bỏ sót quan hệ thật (bài toán
        compliance: bỏ sót nguy hiểm hơn dư thừa ngữ cảnh). Vòng lặp tự dừng khi frontier rỗng - luôn
        kết thúc vì numbers_to_load chỉ tăng, hữu hạn theo số Clause của hợp đồng.

        Returns:
            Tuple (edges, numbers_to_load).
        """
        # matched_articles: Điều/Phụ lục cha của các Khoản đã khớp trực tiếp - CHỈ dùng để tra
        # expand_by_appendix_refs (REFERS_TO_APPENDIX thường trỏ vào node GỐC, không trỏ đích danh
        # Khoản lá vừa khớp) - KHÔNG dùng để "kéo cả Điều".
        matched_articles = sorted({match["article_number_by_number"][n] for n in top_numbers})

        edges: list[dict] = []
        numbers_to_load = list(top_numbers)

        frontier = set(top_numbers) | set(matched_articles)
        while frontier:
            frontier_list = sorted(frontier)
            newly = set()
            newly |= self._context_builder.add_new_edges(
                edges, self._graph.expand_by_relations(self.contract_id, frontier_list, self._ALL_RELATION_TYPES), numbers_to_load
            )
            newly |= self._context_builder.add_new_edges(
                edges, self._graph.expand_by_definitions(self.contract_id, frontier_list), numbers_to_load
            )
            newly |= self._context_builder.add_new_edges(
                edges, self._graph.expand_by_appendix_refs(self.contract_id, frontier_list), numbers_to_load
            )
            frontier = newly

        return edges, numbers_to_load

    def build_context(
        self,
        numbers_to_load: list[str],
        top_numbers: list[str],
        match: MatchState,
        edges: list[dict],
        n_query_texts: int,
    ) -> dict:
        """Bước 4: lấy chi tiết Clause, gắn preamble + metadata hợp đồng, gộp theo Điều cha, dựng cây
        evidences. `n_query_texts` chỉ dùng để LOG, không ảnh hưởng logic.

        Returns:
            dict {"clauses": [...nhóm theo Điều, đã lắp preamble/metadata...], "evidences": [...cây
            {"root", "chain"} cho mỗi Clause khớp trực tiếp...]}.
        """
        clauses = self._context_builder.load_clause_details(self.contract_id, numbers_to_load, match)
        lookup = {c["number"]: c for c in clauses}

        all_edges = edges + self._context_builder.synthesize_appendix_contains_edges(lookup)
        edges_by_from = self._context_builder.index_edges_by_from(all_edges)
        evidences = self._context_builder.build_evidences(top_numbers, lookup, edges_by_from, match)

        clauses.sort(key=lambda c: self._context_builder.sort_key(match)(c["number"]))
        clauses = self._context_builder.attach_preamble(self.contract_id, clauses)
        clauses = self._context_builder.compress_context(clauses)  # no-op hiện tại - xem rag/builder.py

        groups = self._context_builder.group_by_article(clauses)
        metadata_group = self._context_builder.build_metadata_group(self.contract_id)
        if metadata_group:
            groups.insert(0, metadata_group)

        logger.info(
            "Truy hồi clause cho contract_id=%s: gap_margin=%.2f, top_k_ceiling=%d, min_score=%.2f, "
            "n_queries=%d, n_matched=%d, n_clauses=%d, n_articles=%d, n_evidences=%d",
            self.contract_id, self.gap_margin, self.top_k_ceiling, self.min_score, n_query_texts,
            len(top_numbers), len(clauses), len(groups), len(evidences),
        )
        return {"clauses": groups, "evidences": evidences}

    def run(self, query_texts: list[str]) -> dict:
        """Chạy nối tiếp cả 4 bước bằng lời gọi method thường (KHÔNG qua LangGraph) - dùng cho nơi
        cần retrieval trực tiếp, không thuộc luồng chấm 1 mục checklist (xem
        checklist/nodes.py cho cách dùng khác của cùng 4 method này qua LangGraph)."""
        raw_candidates = self.retrieve(query_texts)
        match, top_numbers = self.rerank(raw_candidates)
        edges, numbers_to_load = self.expand(top_numbers, match)
        return self.build_context(numbers_to_load, top_numbers, match, edges, len(query_texts))

    def find_similar_clauses(self, clause_number: str, top_k: int = 5, same_type_only: bool = True) -> list[dict]:
        """Tìm top_k Clause tương tự nội dung nhất với Clause (self.contract_id, clause_number) ở
        CÁC hợp đồng khác - dùng để gợi ý tham khảo cho reviewer khi cần chỉnh sửa lại 1 Điều khoản
        (không quan tâm Điều khoản tham khảo từng "đạt"/"không đạt" checklist gì - đây chỉ là tra cứu
        tương tự thuần tuý, không phải bằng chứng compliance).

        Tái sử dụng vector store/embedding đã có ở knowledge_graph/graph.py (index
        "excerpt_embedding") thay vì dựng lại.

        Args:
            clause_number: Số hiệu Clause nguồn.
            top_k: Số lượng Clause tương tự tối đa cần trả về.
            same_type_only: True thì chỉ xét Clause cùng ClauseType (tên) với Clause nguồn - thu hẹp
                phạm vi cho đúng loại điều khoản (vd "Bảo mật" chỉ so với "Bảo mật"), không lẫn Clause
                tình cờ giống câu chữ nhưng khác bản chất.

        Returns:
            Danh sách dict {contract_id, contract_name, number, title, text, score}, sắp giảm dần theo
            score, KHÔNG chứa Clause nào thuộc contract_id nguồn.

        Raises:
            ClauseNotFoundError: contract_id/clause_number không tồn tại trong graph.
        """
        rows = get_graph().query(GET_CLAUSE_TEXT_AND_TYPE, params={"contract_id": self.contract_id, "number": clause_number})
        if not rows:
            raise ClauseNotFoundError(f"Không tìm thấy Clause number={clause_number!r} ở contract_id={self.contract_id}")
        source_text = rows[0]["text"]
        clause_type = rows[0]["clause_type"] if same_type_only else None

        vector = self._graph.embed_text(source_text)
        results = get_graph().query(
            FIND_SIMILAR_CLAUSES_CROSS_CONTRACT,
            params={
                "top_k": top_k * _SIMILAR_CLAUSES_OVERFETCH_FACTOR,
                "vector": vector,
                "exclude_contract_id": self.contract_id,
                "clause_type": clause_type,
            },
        )

        best_by_clause: dict[tuple[int, str], dict] = {}
        for r in results:
            key = (r["contract_id"], r["number"])
            if key not in best_by_clause or r["score"] > best_by_clause[key]["score"]:
                best_by_clause[key] = r

        similar = sorted(best_by_clause.values(), key=lambda r: r["score"], reverse=True)[:top_k]
        logger.info(
            "Tìm Clause tương tự: contract_id=%s, clause_number=%s, same_type_only=%s, n_found=%d",
            self.contract_id, clause_number, same_type_only, len(similar),
        )
        return [
            {
                "contract_id": r["contract_id"],
                "contract_name": r["contract_name"],
                "number": r["number"],
                "title": r["title"],
                "text": r["text"],
                "score": round(r["score"], 4),
            }
            for r in similar
        ]

    def _select_query_candidates(
        self,
        query_best_by_number: dict[str, float],
        min_score: float,
        gap_margin: float,
    ) -> list[str]:
        """Chọn Clause nào giữ lại cho 1 truy vấn, adaptive theo độ mạnh của kết quả.

        Thay vì luôn lấy đúng K Clause cố định bất kể phân bố điểm:
        - Luôn giữ ứng viên hạng 1 (nếu đạt min_score - sàn tuyệt đối như cũ).
        - Ứng viên hạng 2 trở đi CHỈ giữ thêm nếu điểm đủ gần điểm hạng 1 (trong khoảng gap_margin) -
          chỉ ứng viên thực sự cạnh tranh với hạng 1 mới đáng tin, không phải một ứng viên đuối hơn
          hẳn nhưng tình cờ vẫn qua được ngưỡng sàn. KHÔNG loại ứng viên cùng Điều với ứng viên đã
          chọn - vì retrieval không tự động "kéo cả Điều", nên 1 Khoản khác cùng Điều nhưng điểm đủ
          tốt vẫn phải giữ lại, không thì sẽ bị bỏ sót hoàn toàn.

        Args:
            query_best_by_number: Điểm tốt nhất của từng Clause (theo số hiệu) cho truy vấn này.
            min_score: Sàn điểm tuyệt đối để ứng viên hạng 1 được giữ.
            gap_margin: Khoảng cách điểm tối đa so với hạng 1 để ứng viên hạng 2 trở đi còn được xét.

        Returns:
            Danh sách số hiệu Clause được giữ lại cho truy vấn này.
        """
        candidates = sorted(query_best_by_number, key=lambda n: query_best_by_number[n], reverse=True)
        if not candidates:
            return []

        above_floor = [n for n in candidates if query_best_by_number[n] >= min_score]
        if not above_floor:
            return candidates[:1]  # không ứng viên nào đạt sàn - vẫn giữ 1 ứng viên tốt nhất để
            # khái niệm của query này không bị bỏ trắng hoàn toàn.

        top_score = query_best_by_number[above_floor[0]]
        selected: list[str] = [above_floor[0]]
        for number in above_floor[1:]:
            if len(selected) >= self.top_k_ceiling:
                break
            if query_best_by_number[number] < top_score - gap_margin:
                break  # đã sắp giảm dần theo điểm - qua ngưỡng này thì các ứng viên sau càng yếu hơn
            selected.append(number)
        return selected
