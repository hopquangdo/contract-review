"""Lắp ráp danh sách Clause CUỐI CÙNG (đưa vào LLM đánh giá) từ tập số hiệu đã chọn qua các bước
retrieve/rerank/expand - tra chi tiết từ Neo4j, gắn preamble + metadata hợp đồng, gộp theo Điều cha,
dựng cây "evidences" (quan hệ đồ thị đã dẫn từ mỗi Clause khớp trực tiếp (root) tới các Clause được
kéo theo, vd "Điều 14 dẫn chiếu tới Phụ lục 03, Phụ lục 03 chứa Phụ lục 03.5" - lộ nguyên nhân graph
thay vì chỉ trả 1 danh sách phẳng), nén/khử trùng lặp dùng chung trong pipeline retrieval. Gộp cả 4
trách nhiệm (lắp Clause phẳng/gộp Điều, dựng cây evidences, nén context, khử trùng lặp) vào 1 class
vì đều là các bước xử lý NHỎ, PHỤ THUỘC lẫn nhau trong CÙNG 1 luồng build_context() của
rag/retrieval.py - tách file riêng trước đây chỉ vì "góc nhìn khác trên cùng dữ liệu",
không phải vì độc lập nhau. Dùng bởi checklist/nodes.py::run_build_context qua Retrieval."""

from __future__ import annotations

import logging
from typing import Hashable, TypeVar

from helpers.context import article_sort_key, clause_sort_key
from knowledge_graph.client import get_graph
from knowledge_graph.queries import GET_AGREEMENT_METADATA, GET_CLAUSE_EXCERPTS, GET_CLAUSES_INFO, GET_PREAMBLE_CLAUSE
from schema.retrieval import Evidence, EvidenceNode, MatchState

logger = logging.getLogger(__name__)

K = TypeVar("K", bound=Hashable)


class ContextBuilder:
    """Lắp danh sách Clause cuối cùng + dựng cây evidences + nén/khử trùng lặp cho 1 lượt build
    context. Không giữ state giữa các lần gọi - mọi method THUẦN theo tham số truyền vào/trả ra."""

    def update_best_score(self, store: dict[K, float], key: K, score: float) -> None:
        """Ghi `score` vào `store[key]` CHỈ NẾU chưa có hoặc `score` cao hơn giá trị đang lưu - dùng cho
        cả `best_score_by_number` (theo Clause) lẫn `matched_score_by_chunk` (theo Excerpt) trong
        checklist/nodes.py::run_rerank, vì 1 Clause/Excerpt có thể xuất hiện ở nhiều truy vấn con với điểm khác
        nhau, chỉ giữ điểm tốt nhất."""
        if key not in store or score > store[key]:
            store[key] = score

    def add_new_edges(self, edges: list[dict], new_edges: list[dict], numbers_to_load: list[str]) -> set[str]:
        """Thêm `new_edges` vào `edges` (append, không dedupe cạnh - trùng cạnh vô hại), đồng thời nạp
        thêm số hiệu MỚI (chưa từng có trong `numbers_to_load`) vào cuối danh sách đó. Trả về đúng tập
        số hiệu THỰC SỰ MỚI - dùng làm frontier cho vòng traversal kế tiếp trong checklist/nodes.py::run_expand."""
        newly_added: set[str] = set()
        for e in new_edges:
            edges.append(e)
            if e["number"] not in numbers_to_load:
                numbers_to_load.append(e["number"])
                newly_added.add(e["number"])
        return newly_added

    def load_clause_details(self, contract_id: int, numbers: list[str], match: MatchState) -> list[dict]:
        """Lấy title/article_number/article_title + toàn bộ Excerpt cho từng Clause trong numbers.

        Áp dụng cho cả Clause đã khớp vector search lẫn Clause được kéo thêm qua graph expansion (Clause
        kéo thêm không có trong metadata vector search nên phải tra riêng qua Cypher).

        Args:
            contract_id: ID hợp đồng.
            numbers: Danh sách số hiệu Clause cần lấy chi tiết.
            match: Kết quả bước retrieve/rerank, dùng để lấy lại điểm số đã tính cho các Clause/Excerpt
                đã khớp.

        Returns:
            Danh sách dict Clause (xem _make_clause_dict), bỏ qua số hiệu không tìm thấy trong graph.
        """
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
                    "score": match["matched_score_by_chunk"].get((number, r["chunk_index"])),
                }
                for r in excerpts_by_number.get(number, [])
            ]
            clauses.append(
                self._make_clause_dict(
                    number,
                    info["title"],
                    info["article_number"],
                    info["article_title"],
                    match["best_score_by_number"].get(number),
                    excerpts,
                    is_appendix=info.get("is_appendix", False),
                )
            )
        return clauses

    def sort_key(self, match: MatchState):
        """Trả về key sắp xếp: Clause đã khớp vector search trước (điểm cao trước), Clause chỉ được
        kéo thêm theo Điều (không có điểm) xếp sau cùng theo đúng thứ tự số hiệu."""

        def key(number: str):
            score = match["best_score_by_number"].get(number)
            return (0, -score) if score is not None else (1, number)

        return key

    def group_by_article(self, clauses: list[dict]) -> list[dict]:
        """Gộp danh sách Clause (Khoản) phẳng về theo Điều cha.

        Thứ tự Điều LUÔN theo số hiệu tăng dần (Điều trước Phụ lục) - KHÔNG theo thứ hạng match/score dù
        đầu vào "clauses" có thể đã được sort theo score trước đó (xem rag/retrieval.py::
        build_context_stage). Cố định thứ tự này (thay vì "matched-trước") để 2 lượt gọi LLM khác nhau
        trên CÙNG 1 hợp đồng (khác câu hỏi checklist nhưng trùng lặp 1 phần Điều đã truy hồi) tạo ra
        PHẦN ĐẦU văn bản context giống hệt nhau càng nhiều càng tốt - tối đa hoá cơ hội OpenAI prompt
        cache (chỉ cache theo tiền tố token trùng khớp tuyệt đối, thứ tự ngẫu nhiên theo score sẽ phá vỡ
        tiền tố này ngay từ Điều đầu tiên). Thứ tự Khoản trong từng Điều luôn tăng dần theo số hiệu bất
        kể thứ hạng match.

        Args:
            clauses: Danh sách dict Clause phẳng (xem _make_clause_dict).

        Returns:
            Danh sách dict nhóm theo Điều (đã sắp theo số hiệu tăng dần), mỗi nhóm có
            article_number/article_title/score/clauses/text.
        """
        groups: dict[str, dict] = {}
        for c in clauses:
            art = c["article_number"]
            if art not in groups:
                groups[art] = {
                    "article_number": art, "article_title": c["article_title"], "score": None, "clauses": [],
                    "is_appendix": c.get("is_appendix", False),
                }
            groups[art]["clauses"].append(c)
            if c["score"] is not None and (groups[art]["score"] is None or c["score"] > groups[art]["score"]):
                groups[art]["score"] = c["score"]

        result = []
        for art in sorted(groups, key=article_sort_key):
            g = groups[art]
            g["clauses"].sort(key=lambda c: clause_sort_key(c["number"]))
            # Phụ lục hiển thị "Phụ lục <nhãn>" (bỏ tiền tố "PL" nội bộ), khác "Điều" - xem
            # ingestion/section_splitter.py cho cách number="PL<nhãn>" được sinh ra.
            label = g["article_number"][2:] if g["is_appendix"] else g["article_number"]
            prefix = "Phụ lục" if g["is_appendix"] else "Điều"
            header = f"{prefix} {label}. {g['article_title']}" if g["article_title"] else f"{prefix} {label}"
            g["text"] = header + "\n\n" + "\n\n".join(c["text"] for c in g["clauses"])
            result.append(g)
        return result

    def build_metadata_group(self, contract_id: int) -> dict | None:
        """Dựng Điều "ảo" đính kèm luật áp dụng + phương thức giải quyết tranh chấp.

        Tra cứu trực tiếp theo contract_id (GoverningLaw/DisputeResolution), KHÔNG qua vector search vì
        đây là fact cố định của cả hợp đồng, không phải nội dung cần so khớp độ liên quan.

        Args:
            contract_id: ID hợp đồng.

        Returns:
            dict nhóm Điều "ảo" (article_number="meta"), hoặc None nếu hợp đồng không có dữ liệu này
            (LLM extraction không trích được, vd hợp đồng không ghi rõ).
        """
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
        clause = self._make_clause_dict(
            "meta", "Luật áp dụng & giải quyết tranh chấp", "meta", "Luật áp dụng & giải quyết tranh chấp", None,
            excerpts,
        )
        return {
            "article_number": "meta", "article_title": "Luật áp dụng & giải quyết tranh chấp", "score": None,
            "clauses": [clause], "text": text,
        }

    def attach_preamble(self, contract_id: int, clauses: list[dict]) -> list[dict]:
        """Chèn Clause preamble (phần mở đầu hợp đồng: các bên, người đại diện/chức vụ, ngày ký...) vào
        ĐẦU danh sách - LUÔN có, không qua vector search (xem ingestion/section_splitter.py, số hiệu
        "0"). Trả về list MỚI (không mutate `clauses` gốc)."""
        preamble_records = get_graph().query(GET_PREAMBLE_CLAUSE, params={"contract_id": contract_id})
        if not preamble_records:
            logger.warning("Không tìm thấy clause preamble cho contract_id=%s", contract_id)
            return clauses
        p0 = preamble_records[0]
        preamble_excerpts = [{"chunk_index": r["chunk_index"], "text": r["text"], "score": None} for r in preamble_records]
        preamble_clause = self._make_clause_dict(
            p0["number"], p0["title"], p0["article_number"], p0["article_title"], None, preamble_excerpts,
        )
        return [preamble_clause, *clauses]

    def synthesize_appendix_contains_edges(self, lookup: dict[str, dict]) -> list[dict]:
        """Cạnh CONTAINS (gốc Phụ lục -> mục con) KHÔNG phải cạnh Neo4j thật (chỉ chung article_number) -
        tự dựng tại đây, CHỈ nối những mục con THỰC SỰ đã có mặt trong `lookup` (vd tự nó cũng khớp trực
        tiếp, hoặc được REFERS_TO_APPENDIX trỏ đích danh) - không dump toàn bộ mục con."""
        edges: list[dict] = []
        for number, info in lookup.items():
            if info.get("is_appendix") and info["article_number"] == number:  # đúng node gốc Phụ lục
                for other_number, other_info in lookup.items():
                    if other_number != number and other_info.get("is_appendix") and other_info["article_number"] == number:
                        edges.append({"number": other_number, "from": number, "to": other_number, "relation": "CONTAINS"})
        return edges

    def index_edges_by_from(self, edges: list[dict]) -> dict[str, list[dict]]:
        edges_by_from: dict[str, list[dict]] = {}
        for e in edges:
            edges_by_from.setdefault(e["from"], []).append(e)
        return edges_by_from

    def compress_context(self, clauses: list[dict], max_chars: int | None = None) -> list[dict]:
        """Nén/cắt bớt context trước khi đưa vào LLM - HIỆN CHƯA CÓ LOGIC NÉN THẬT NÀO trong pipeline
        (mọi Excerpt của Clause đã chọn được đưa NGUYÊN VẸN vào LLM đánh giá). Method này là placeholder
        NO-OP để khớp vị trí trong sơ đồ tổ chức lại `src/`, KHÔNG PHẢI tính năng đã kiểm chứng - mặc
        định trả về nguyên `clauses` không đổi trừ khi chủ động truyền `max_chars`. Nếu sau này cần nén
        context thật (context quá dài vượt budget LLM), viết logic thật vào đây.

        No-op nếu không truyền `max_chars` (hành vi mặc định, giữ nguyên pipeline hiện tại). Nếu có
        truyền, cắt bớt "text" của từng Clause về tối đa `max_chars` ký tự (cắt thô, không tóm tắt)."""
        if max_chars is None:
            return clauses
        return [{**c, "text": c["text"][:max_chars]} for c in clauses]

    def build_evidences(
        self, top_numbers: list[str], lookup: dict[str, dict], edges_by_from: dict[str, list[dict]], match: MatchState,
    ) -> list[Evidence]:
        """Dựng đủ cây evidences cho mọi Clause khớp trực tiếp (top_numbers) - bỏ qua root không tìm
        thấy chi tiết (số hiệu bị mất giữa các bước, không nên xảy ra nhưng phòng hờ)."""
        top_numbers_set = set(top_numbers)
        evidences: list[Evidence] = []
        for root_number in top_numbers:
            if root_number not in lookup:
                continue
            visited = {root_number}
            evidences.append({
                "root": self._node_info(root_number, lookup, top_numbers_set, match),
                "chain": self._build_evidence_children(root_number, edges_by_from, lookup, top_numbers_set, match, visited),
            })
        return evidences

    def _make_clause_dict(
        self,
        number: str, title: str, article_number: str, article_title: str, score: float | None,
        excerpts: list[dict], is_appendix: bool = False,
    ) -> dict:
        """Dựng dict 1 Clause trả về cho phần gọi ngoài (checklist/evaluator.py, frontend Evidence).

        Dùng chung cho mọi nguồn dựng Clause (đã khớp vector search, kéo thêm theo Điều, preamble, hay
        Phụ lục) để không lặp lại cùng 1 cấu trúc dict ở nhiều nơi (từng là bug tiềm ẩn: thêm field
        mới phải nhớ sửa đủ mọi chỗ dựng dict thủ công).

        Returns:
            dict Clause với các field number/title/article_number/article_title/score/text/excerpts/
            is_appendix.
        """
        return {
            "number": number,
            "title": title,
            "article_number": article_number,
            "article_title": article_title,
            "score": round(score, 4) if score is not None else None,
            "text": "\n\n".join(e["text"] for e in excerpts),
            "excerpts": excerpts,
            "is_appendix": is_appendix,
        }

    def _node_info(self, number: str, lookup: dict[str, dict], top_numbers: set[str], match: MatchState) -> EvidenceNode:
        """Dựng 1 node cây evidences (không kèm "relation"/"children" - caller tự gắn thêm)."""
        info = lookup[number]
        return {
            "number": info["number"],
            "title": info["title"],
            "is_appendix": info.get("is_appendix", False),
            "matched": number in top_numbers,
            "score": round(match["best_score_by_number"][number], 4) if number in top_numbers else None,
            "content": info["text"],
        }

    def _build_evidence_children(
        self, number: str, edges_by_from: dict[str, list[dict]], lookup: dict[str, dict],
        top_numbers: set[str], match: MatchState, visited: set[str],
    ) -> list[EvidenceNode]:
        """Đệ quy dựng danh sách "children" của 1 node trong cây evidences, theo đúng cạnh đã ghi lại
        lúc mở rộng (edges_by_from, đã lập chỉ mục theo "from" = nguồn THẬT của quan hệ) - guard chu
        trình bằng visited (riêng cho mỗi root), không lấy lại Neo4j. Dùng edge["to"] (đích THẬT) làm
        con, KHÔNG dùng edge["number"] (chỉ để nạp numbers_to_load, có thể ngược chiều nếu number ==
        chính "from" khi quan hệ thật sự trỏ NGƯỢC vào node đang truy vấn - xem docstring class
        Graph ở knowledge_graph/graph.py)."""
        children = []
        for edge in edges_by_from.get(number, []):
            child_number = edge["to"]
            if child_number in visited or child_number not in lookup:
                continue
            visited.add(child_number)
            node = self._node_info(child_number, lookup, top_numbers, match)
            node["relation"] = edge["relation"]
            node["children"] = self._build_evidence_children(child_number, edges_by_from, lookup, top_numbers, match, visited)
            children.append(node)
        return children
