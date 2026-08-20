"""Xuất "mục lục" (Section -> Điều -> Khoản, kèm Excerpt nếu cần) của 1 hợp đồng ĐÃ BUILD trong
graph Neo4j ra text, để đối chiếu thủ công với văn bản gốc (vd kiểm tra tách Điều/Khoản/Excerpt có
đúng thứ tự, có sót/lặp số hiệu nào không). Kèm clause_type (phân loại đã build) - phân biệt với
scripts/export_toc_regex.py (chạy regex thuần trực tiếp trên .md, không cần graph).

Usage:
    python scripts/export_toc_graph.py --contract-id 9 [--out path.txt] [--with-excerpts]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from knowledge_graph.client import get_graph  # noqa: E402

_DEFAULT_OUT_DIR = Path("data/output/toc_graph")

_SECTIONS_QUERY = """
MATCH (a:Agreement {contract_id: $contract_id})-[:HAS_SECTION]->(s:Section)
RETURN s.number AS number, s.title AS title
"""

_CLAUSES_QUERY = """
MATCH (sec:Section {number: $section_number, agreement_id: $contract_id})-[:HAS_CLAUSE]->(c:Clause)
OPTIONAL MATCH (c)-[:HAS_TYPE]->(ct:ClauseType)
RETURN c.number AS number, c.title AS title, c.article_number AS article_number,
       c.article_title AS article_title, ct.name AS clause_type
"""

_EXCERPTS_QUERY = """
MATCH (c:Clause {number: $clause_number, agreement_id: $contract_id})-[:HAS_EXCERPT]->(e:Excerpt)
RETURN e.chunk_index AS chunk_index, e.text AS text
ORDER BY e.chunk_index
"""


def _natural_sort_key(number: str) -> list[tuple[int, int | str]]:
    """Sắp xếp số hiệu kiểu '9.2' đúng thứ tự SỐ HỌC (không phải thứ tự chuỗi ký tự, vốn sẽ đặt
    '10' trước '2'). Phần không phải số (vd 'PL02') xếp sau mọi số hiệu số học thuần."""
    key: list[tuple[int, int | str]] = []
    for part in number.split("."):
        try:
            key.append((0, int(part)))
        except ValueError:
            key.append((1, part))
    return key


def build_toc(contract_id: int, with_excerpts: bool) -> str:
    graph = get_graph()
    sections = graph.query(_SECTIONS_QUERY, params={"contract_id": contract_id})
    sections.sort(key=lambda s: _natural_sort_key(s["number"]))

    lines: list[str] = [f"# Graph TOC - contract_id={contract_id}"]
    for s in sections:
        lines.append(f"== Section {s['number']}. {s['title']} ==")
        clauses = graph.query(_CLAUSES_QUERY, params={"section_number": s["number"], "contract_id": contract_id})
        clauses.sort(key=lambda c: _natural_sort_key(c["number"]))
        last_article_number = None
        for c in clauses:
            is_article = c["number"] == c["article_number"]
            # Điều bị tách thành nhiều Khoản con KHÔNG tồn tại như 1 Clause riêng trong graph (chỉ
            # có các Khoản con) - tự dựng lại dòng tiêu đề "Điều N. Tiêu đề" từ article_number/
            # article_title của Khoản con đầu tiên để mục lục đọc đúng thứ tự hợp đồng gốc, thay vì
            # chỉ thấy các Khoản "1.1", "1.2"... trồi lên không rõ thuộc Điều nào.
            if not is_article and c["article_number"] != last_article_number:
                lines.append(f"Điều {c['article_number']}. {c['article_title']}")
            last_article_number = c["article_number"]
            title_part = f" {c['title']}" if c["title"] else ""
            if is_article:
                lines.append(f"Điều {c['number']} [{c['clause_type']}]{title_part}")
            else:
                # Số hiệu Khoản không được lưu quan hệ cha-con TƯỜNG MINH trong graph (chỉ chung
                # article_number) - suy ra độ sâu lồng cấp NGẦM từ số dấu chấm trong number (vd
                # "1.2" độ sâu 1, "1.2.1" độ sâu 2) để mục lục hiển thị đúng phân cấp thật của văn
                # bản gốc, dù bản thân graph lưu chúng phẳng ngang hàng.
                depth = c["number"].count(".")
                indent = "  " * depth
                lines.append(f"{indent}Khoản {c['number']} [{c['clause_type']}]{title_part}")
            if with_excerpts:
                excerpts = graph.query(_EXCERPTS_QUERY, params={"clause_number": c["number"], "contract_id": contract_id})
                for e in excerpts:
                    text_oneline = " ".join(e["text"].split())
                    lines.append(f"    - Excerpt {e['chunk_index']}: {text_oneline}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contract-id", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None, help="Ghi ra file cụ thể - mặc định data/output/toc_graph/toc_contract{id}.txt")
    parser.add_argument("--with-excerpts", action="store_true", help="Kèm nội dung từng Excerpt bên dưới mỗi Khoản")
    args = parser.parse_args()

    toc = build_toc(args.contract_id, args.with_excerpts)
    out_path = args.out or (_DEFAULT_OUT_DIR / f"toc_contract{args.contract_id}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(toc, encoding="utf-8")
    print(f"Đã xuất mục lục (graph) contract_id={args.contract_id} vào {out_path}")


if __name__ == "__main__":
    main()
