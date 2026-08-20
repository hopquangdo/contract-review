"""Benchmark chất lượng tách Điều/Khoản (mục lục) trên số hiệu "x.y" tìm thấy trong file .md nguồn.

2 chế độ:
- Mặc định: so khớp với Clause ĐÃ CÓ THẬT trong graph Neo4j (đánh giá đúng dữ liệu đang thực sự nằm
  trong graph, không tốn thời gian/chi phí chạy lại pipeline).
- `--from-source`: chạy TRỰC TIẾP `ingestion.section_splitter.split_into_sections_and_clauses()`
  trên file .md, KHÔNG cần graph đã build - dùng để hồi quy nhanh (regression check) mỗi khi sửa
  regex/quy tắc tách, xác nhận không làm sập recall trước khi build lại graph thật (tốn LLM).

Tự động khớp Agreement.name (contract_name = Path(file).stem, xem scripts/build_graph.py) với file
trong data/input/ (thử "{name}.md" rồi "{name}.parsed.md") - không cần khai báo tay từng cặp.

Usage:
    python scripts/benchmark_toc_extraction.py [--contract-id 8 9 ...] [--input-dir data/input] [--out path.json]
    python scripts/benchmark_toc_extraction.py --from-source [--input-dir data/input] [--out path.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from ingestion.section_splitter import compute_numbering_diagnostics, split_into_sections_and_clauses  # noqa: E402
from utils.text_cleanup import normalize_markdown  # noqa: E402
from knowledge_graph.client import get_graph  # noqa: E402

_AGREEMENTS_QUERY = "MATCH (a:Agreement) RETURN a.contract_id AS contract_id, a.name AS name ORDER BY a.contract_id"
_CLAUSE_NUMBERS_QUERY = "MATCH (c:Clause {agreement_id: $contract_id}) RETURN c.number AS number"


def _resolve_source_file(name: str, input_dir: Path) -> Path | None:
    for suffix in (".md", ".parsed.md"):
        candidate = input_dir / f"{name}{suffix}"
        if candidate.exists():
            return candidate
    return None


def benchmark_contract(contract_id: int, name: str, input_dir: Path) -> dict | None:
    source = _resolve_source_file(name, input_dir)
    if source is None:
        return None

    graph = get_graph()
    rows = graph.query(_CLAUSE_NUMBERS_QUERY, params={"contract_id": contract_id})
    seen_numbers = {r["number"] for r in rows}

    text = normalize_markdown(source.read_text(encoding="utf-8"))
    diagnostics = compute_numbering_diagnostics(text, seen_numbers)
    return {"contract_id": contract_id, "name": name, "source_file": str(source), "n_clauses_in_graph": len(seen_numbers), **diagnostics}


def benchmark_from_source(source: Path) -> dict:
    """Chạy split_into_sections_and_clauses() TRỰC TIẾP trên 1 file .md - không đọc/ghi graph.

    Dùng cho hồi quy nhanh: sửa xong regex trong ingestion/section_splitter.py hay
    ingestion/text_cleanup.py thì chạy `--from-source` để biết ngay recall có tụt không, không cần
    build lại graph thật (tốn LLM extraction + embedding).
    """
    text = normalize_markdown(source.read_text(encoding="utf-8"))
    _sections, clauses = split_into_sections_and_clauses(text)
    seen_numbers = {c["number"] for c in clauses}
    diagnostics = compute_numbering_diagnostics(text, seen_numbers)
    return {"name": source.stem, "source_file": str(source), "n_clauses": len(seen_numbers), **diagnostics}


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contract-id", type=int, nargs="*", default=None, help="Chỉ benchmark các contract_id này - mặc định TẤT CẢ hợp đồng trong graph (bỏ qua nếu dùng --from-source)")
    parser.add_argument("--from-source", action="store_true", help="Chạy trực tiếp trên mọi file .md trong --input-dir, KHÔNG cần graph đã build - dùng để hồi quy nhanh sau khi sửa regex")
    parser.add_argument("--input-dir", type=Path, default=Path("data/input"))
    parser.add_argument("--out", type=Path, default=None, help="Ghi báo cáo JSON ra file (tuỳ chọn)")
    args = parser.parse_args()

    if args.from_source:
        results = [benchmark_from_source(p) for p in sorted(args.input_dir.glob("*.md"))]
        skipped = []
        id_label = "name"
    else:
        graph = get_graph()
        agreements = graph.query(_AGREEMENTS_QUERY)
        if args.contract_id:
            wanted = set(args.contract_id)
            agreements = [a for a in agreements if a["contract_id"] in wanted]

        results = []
        skipped = []
        for a in agreements:
            result = benchmark_contract(a["contract_id"], a["name"], args.input_dir)
            if result is None:
                skipped.append(a)
                continue
            results.append(result)
        id_label = "contract_id"

    print(f"{id_label:<12}{'recall':<10}{'n_candidates':<14}{'n_matched':<11}{'n_missing':<11}{'name'}")
    for r in results:
        row_id = r.get("contract_id", r["name"])
        print(f"{row_id:<12}{r['recall']*100:>6.1f}%   {r['n_candidates']:<14}{r['n_matched']:<11}{r['n_missing']:<11}{r['name']}")
        if r["missing_numbers"]:
            print(f"    thiếu: {r['missing_numbers']}")

    if skipped:
        print(f"\nBỏ qua {len(skipped)} hợp đồng không tìm thấy file nguồn trong {args.input_dir}: {[a['name'] for a in skipped]}")

    if results:
        avg_recall = sum(r["recall"] for r in results) / len(results)
        total_missing = sum(r["n_missing"] for r in results)
        print(f"\nTrung bình recall: {avg_recall*100:.2f}% trên {len(results)} hợp đồng, tổng {total_missing} số hiệu còn thiếu.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã ghi báo cáo vào {args.out}")


if __name__ == "__main__":
    main()
