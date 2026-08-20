"""Xuất "mục lục" (Section -> Điều -> Khoản) tách được BẰNG REGEX THUẦN

(ingestion.section_splitter.split_into_sections_and_clauses), KHÔNG cần graph Neo4j/LLM - dùng để
xem NGAY kết quả regex đang tách ra sao trên 1 file .md nguồn, đối chiếu nhanh với văn bản gốc khi
sửa regex trong ingestion/section_splitter.py hay ingestion/text_cleanup.py. Phân biệt với
scripts/export_toc_graph.py (đọc từ graph Neo4j đã build thật, kèm clause_type).

Usage:
    python scripts/export_toc_regex.py --input data/input/BM01.md
    python scripts/export_toc_regex.py --all [--input-dir data/input]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Console Windows mặc định dùng cp1252 - tên file/nội dung tiếng Việt (dấu) làm print() sập giữa
# chừng batch --all. Ép stdout/stderr UTF-8 để chạy được trên mọi terminal, không phụ thuộc
# codepage hệ thống.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from ingestion.section_splitter import split_into_sections_and_clauses  # noqa: E402
from utils.text_cleanup import normalize_markdown  # noqa: E402

_DEFAULT_OUT_DIR = Path("data/output/toc_regex")


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


def build_regex_toc(source: Path) -> str:
    text = normalize_markdown(source.read_text(encoding="utf-8"))
    sections, clauses = split_into_sections_and_clauses(text)
    sections = sorted(sections, key=lambda s: _natural_sort_key(s["number"]))
    clauses_by_number = {c["number"]: c for c in clauses}

    lines: list[str] = [f"# Regex TOC - {source.name}", f"Tổng số Clause tách được: {len(clauses)}", ""]

    # Preamble (số hiệu "0") không thuộc Section nào - liệt kê riêng trước mọi Section.
    preamble = clauses_by_number.get("0")
    if preamble:
        lines.append(f"[preamble] {preamble['title']}")
        lines.append("")

    assigned_numbers = {"0"} if preamble else set()
    for s in sections:
        lines.append(f"== Section {s['number']}. {s['title']} ==")
        section_clause_numbers = sorted(s["clause_numbers"], key=_natural_sort_key)
        last_article_number = None
        for number in section_clause_numbers:
            c = clauses_by_number.get(number)
            if c is None:
                lines.append(f"  !! Thiếu Clause cho số hiệu {number} (có trong section['clause_numbers'] nhưng không có trong clauses)")
                continue
            assigned_numbers.add(number)
            is_article = c["number"] == c["article_number"]
            if not is_article and c["article_number"] != last_article_number:
                lines.append(f"Điều {c['article_number']}. {c['article_title']}")
            last_article_number = c["article_number"]
            title_part = f" {c['title']}" if c["title"] else ""
            appendix_tag = " [appendix]" if c.get("is_appendix") else ""
            depth = c["number"].count(".")
            if is_article:
                lines.append(f"Điều {c['number']}{appendix_tag}{title_part}")
            else:
                indent = "  " * depth
                lines.append(f"{indent}Khoản {c['number']}{appendix_tag}{title_part}")
        lines.append("")

    # Clause tách được nhưng KHÔNG thuộc Section nào đã liệt kê ở trên (dấu hiệu bug regex) - liệt
    # kê riêng để không bị lọt mất khỏi báo cáo.
    orphans = [c for n, c in clauses_by_number.items() if n not in assigned_numbers]
    if orphans:
        lines.append("== Clause KHÔNG gán được vào Section nào (kiểm tra lại regex Section) ==")
        for c in sorted(orphans, key=lambda c: _natural_sort_key(c["number"])):
            title_part = f" {c['title']}" if c["title"] else ""
            lines.append(f"  {c['number']}{title_part}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=None, help="1 file .md cụ thể cần xuất")
    parser.add_argument("--all", action="store_true", help="Xuất mọi file .md trong --input-dir")
    parser.add_argument("--input-dir", type=Path, default=Path("data/input"))
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    args = parser.parse_args()

    if not args.input and not args.all:
        parser.error("Cần truyền --input <file.md> hoặc --all")

    sources = sorted(args.input_dir.glob("*.md")) if args.all else [args.input]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        if not source.exists():
            print(f"Bỏ qua - không tìm thấy file: {source}")
            continue
        toc = build_regex_toc(source)
        out_path = args.out_dir / f"toc_{source.stem}.txt"
        out_path.write_text(toc, encoding="utf-8")
        n_clauses = toc.split("Tổng số Clause tách được: ", 1)[1].split("\n", 1)[0]
        print(f"{source.name}: {n_clauses} clauses -> {out_path}")


if __name__ == "__main__":
    main()
