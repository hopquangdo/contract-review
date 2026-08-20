"""Công cụ dòng lệnh để convert 1 tài liệu hợp đồng (PDF/DOCX/...) sang Markdown, dùng lại đúng
service parse_to_markdown() mà API upload (services/contract_service.py) đang dùng - không viết
lại logic parse riêng cho CLI.

Usage: python scripts/convert_to_markdown.py --input path/to/contract.pdf [--out path/to/out.md]
Không truyền --out -> ghi cạnh file gốc, cùng tên, đuôi ".parsed.md" (đúng định dạng input mà
scripts/build_graph.py đang mong đợi).

python scripts/convert_to_markdown.py --input path/to/contract.pdf
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from ingestion.docling_parser import parse_to_markdown  # noqa: E402
from utils.text_cleanup import normalize_markdown  # noqa: E402

logger = logging.getLogger(__name__)

_MARKDOWN_SUFFIXES = {".md", ".txt"}


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Đường dẫn tài liệu gốc (PDF/DOCX/...)")
    parser.add_argument(
        "--out", default=None,
        help="Đường dẫn ghi file .md - mặc định cùng thư mục/tên file gốc, đuôi '.parsed.md'",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    raw = input_path.read_bytes()

    # Cùng nhánh rẽ như contract_service.import_contract(): .md/.txt chỉ cần chuẩn hoá khoảng
    # trắng, các định dạng khác (PDF/DOCX/...) mới cần qua docling parse_to_markdown().
    if input_path.suffix.lower() in _MARKDOWN_SUFFIXES:
        logger.info("Input đã là markdown/text, chỉ chuẩn hoá: %s", input_path)
        markdown = normalize_markdown(raw.decode("utf-8"))
    else:
        logger.info("Bắt đầu convert sang markdown bằng docling: %s", input_path)
        markdown = parse_to_markdown(input_path.name, raw)  # đã chuẩn hoá bên trong

    out_path = Path(args.out) if args.out else input_path.with_suffix(".parsed.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    logger.info("Đã ghi markdown (%d ký tự) vào '%s'.", len(markdown), out_path)


if __name__ == "__main__":
    main()
