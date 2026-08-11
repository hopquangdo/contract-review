"""Công cụ dòng lệnh để build graph tri thức cho 1 hợp đồng.

Usage: python scripts/build_graph.py --contract path/to/contract.parsed.md [--contract-id 5]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from knowledge_graph.builder import build_graph, next_contract_id  # noqa: E402
from ingestion.section_splitter import split_into_sections_and_clauses  # noqa: E402
from ingestion.text_cleanup import normalize_markdown  # noqa: E402
from llm.graph_extraction import extract_relations  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, help="Path to contract .parsed.md")
    parser.add_argument(
        "--contract-id", type=int, default=None, help="Mặc định: tự tăng (số hợp đồng tiếp theo)"
    )
    args = parser.parse_args()

    text = normalize_markdown(Path(args.contract).read_text(encoding="utf-8"))
    contract_name = Path(args.contract).stem

    sections, clauses = split_into_sections_and_clauses(text)
    logger.info("Tách được %d Phần, %d Clause từ '%s'.", len(sections), len(clauses), contract_name)

    logger.info("Gọi LLM trích xuất parties/governing_law/dispute_resolution/clause_type/quan hệ chéo...")
    extraction, extraction_usage = extract_relations(contract_name, clauses)
    logger.info("  parties: %s", [p.name for p in extraction.parties])
    logger.info("  governing_law: %s", extraction.governing_law)
    n_refers = sum(len(c.refers_to) for c in extraction.clauses)
    n_depends = sum(len(c.depends_on) for c in extraction.clauses)
    n_exception = sum(len(c.exception_to) for c in extraction.clauses)
    logger.info("  quan hệ chéo: REFERS_TO=%d, DEPENDS_ON=%d, EXCEPTION_TO=%d", n_refers, n_depends, n_exception)

    contract_id = args.contract_id if args.contract_id is not None else next_contract_id()

    n_cross = build_graph(
        contract_id, contract_name, sections, clauses, extraction, extraction_usage, source_filename=Path(args.contract).name
    )
    logger.info(
        "Đã build graph đầy đủ cho contract_id=%d (%d quan hệ chéo giữa các Điều) + embedding.", contract_id, n_cross
    )


if __name__ == "__main__":
    main()
