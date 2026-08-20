"""Xuất TOÀN BỘ Clause + quan hệ đồ thị THẬT của 1 hợp đồng (không qua checklist/retrieval - đọc
thẳng Neo4j) ra 1 file JSON, dùng cho graph.html (list phẳng mọi Điều khoản, click xem liên kết) -
khác với evidence_graph (chỉ hiện Khoản liên quan tới 1 câu hỏi checklist cụ thể), file này cho xem
HẾT quan hệ đã trích xuất trong cả hợp đồng để kiểm tra/khám phá graph.

Usage: python scripts/build_contract_graph_export.py --contract-id 4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from knowledge_graph.client import get_graph  # noqa: E402

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_DIR = _ROOT / "data" / "output" / "eval"

_RELATION_TYPES = ["REFERS_TO", "DEPENDS_ON", "EXCEPTION_TO", "REFERS_TO_APPENDIX"]


def export_contract_graph(contract_id: int) -> dict:
    graph = get_graph()

    name_rows = graph.query("MATCH (a:Agreement {contract_id: $id}) RETURN a.name AS name", params={"id": contract_id})
    contract_name = name_rows[0]["name"] if name_rows else str(contract_id)

    clause_rows = graph.query(
        """
        MATCH (c:Clause {agreement_id: $id})
        WHERE coalesce(c.is_preamble, false) = false
        RETURN c.number AS number, c.title AS title, coalesce(c.is_appendix, false) AS is_appendix,
               c.article_number AS article_number, c.article_title AS article_title, c.text AS text
        ORDER BY c.number
        """,
        params={"id": contract_id},
    )

    edge_rows = graph.query(
        """
        MATCH (a:Clause {agreement_id: $id})-[r]-(b:Clause {agreement_id: $id})
        WHERE type(r) IN $rel_types
        RETURN DISTINCT startNode(r).number AS from_number, endNode(r).number AS to_number, type(r) AS relation
        """,
        params={"id": contract_id, "rel_types": _RELATION_TYPES},
    )

    defines_rows = graph.query(
        "MATCH (c:Clause {agreement_id:$id})-[:USES_TERM]->(d:Definition)<-[:DEFINES]-(src:Clause) "
        "RETURN DISTINCT src.number AS from_number, c.number AS to_number, d.term AS term",
        params={"id": contract_id},
    )
    edges = [{"from": r["from_number"], "to": r["to_number"], "relation": r["relation"]} for r in edge_rows]
    edges += [{"from": r["from_number"], "to": r["to_number"], "relation": "DEFINES"} for r in defines_rows]

    # CONTAINS: gốc Phụ lục -> mục con - không phải cạnh Neo4j thật (chỉ chung article_number,
    # xem rag/retrieval/vector_retriever.py) - tự dựng ở đây để xem được ĐẦY ĐỦ cấu trúc Phụ lục.
    by_article: dict[str, list[str]] = {}
    for c in clause_rows:
        if c["is_appendix"]:
            by_article.setdefault(c["article_number"], []).append(c["number"])
    for root, members in by_article.items():
        for m in members:
            if m != root:
                edges.append({"from": root, "to": m, "relation": "CONTAINS"})

    logger.info("contract_id=%d: %d clause, %d cạnh (kể cả CONTAINS suy ra).", contract_id, len(clause_rows), len(edges))
    return {"contract_id": contract_id, "contract_name": contract_name, "clauses": clause_rows, "edges": edges}


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-id", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None, help="Mặc định: data/output/eval/contract_graph_contract<id>.json")
    args = parser.parse_args()

    data = export_contract_graph(args.contract_id)

    out_path = args.out or (_OUTPUT_DIR / f"contract_graph_contract{args.contract_id}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Đã ghi '%s' (%.0f KB) - mở graph.html rồi upload file này để xem.", out_path, out_path.stat().st_size / 1024)


if __name__ == "__main__":
    main()
