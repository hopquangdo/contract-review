"""Xuất toàn bộ (hoặc 1 hợp đồng) graph tri thức trong Neo4j ra file JSON để debug/kiểm tra thủ
công - không qua truy vấn nghiệp vụ nào, chỉ dump thẳng node + quan hệ.

Usage: python scripts/export_graph.py [--contract-id 1] [--out path.json] [--include-embeddings]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from knowledge_graph.client import get_graph  # noqa: E402

# elementId(n)/type(r) đủ để dựng lại cấu trúc graph trong JSON (source/target/type) mà không cần
# phụ thuộc APOC - chạy được trên mọi Neo4j 5.x không cần cài thêm plugin.
_NODES_QUERY = """
MATCH (n)
WHERE $contract_id IS NULL OR n.agreement_id = $contract_id OR n.contract_id = $contract_id
RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties
"""

_RELATIONSHIPS_QUERY = """
MATCH (a)-[r]->(b)
WHERE $contract_id IS NULL
   OR a.agreement_id = $contract_id OR a.contract_id = $contract_id
   OR b.agreement_id = $contract_id OR b.contract_id = $contract_id
RETURN elementId(a) AS source, elementId(b) AS target, type(r) AS type, properties(r) AS properties
"""


def export_graph(contract_id: int | None, include_embeddings: bool) -> dict:
    graph = get_graph()
    nodes = graph.query(_NODES_QUERY, params={"contract_id": contract_id})
    relationships = graph.query(_RELATIONSHIPS_QUERY, params={"contract_id": contract_id})

    if not include_embeddings:
        # Vector embedding (vd Excerpt.embedding, hàng nghìn float) làm JSON phình to vô ích cho
        # mục đích debug thủ công - loại bỏ mặc định, bật lại bằng --include-embeddings nếu cần.
        for node in nodes:
            node["properties"].pop("embedding", None)

    return {"nodes": nodes, "relationships": relationships}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contract-id", type=int, default=None, help="Chỉ xuất 1 hợp đồng - mặc định xuất toàn bộ graph")
    parser.add_argument("--out", type=Path, default=Path("data/benchmark/graph_export.json"))
    parser.add_argument("--include-embeddings", action="store_true", help="Giữ lại vector embedding trong output (mặc định bỏ)")
    args = parser.parse_args()

    data = export_graph(args.contract_id, args.include_embeddings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Da xuat {len(data['nodes'])} node, {len(data['relationships'])} quan he vao {args.out}")


if __name__ == "__main__":
    main()
