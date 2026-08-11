"""Nghiệp vụ quản lý hợp đồng: import, liệt kê, xem, xoá."""

from __future__ import annotations

import logging
from pathlib import Path

from knowledge_graph.builder import build_graph, delete_contract, next_contract_id
from knowledge_graph.client import get_graph
from knowledge_graph.queries import GET_CONTRACT_STATUS, LIST_CONTRACTS
from ingestion.docling_parser import parse_to_markdown
from ingestion.section_splitter import split_into_sections_and_clauses
from ingestion.text_cleanup import normalize_markdown
from llm.graph_extraction import extract_relations

logger = logging.getLogger(__name__)


class ContractNotFoundError(Exception):
    """Báo hiệu hợp đồng được yêu cầu không tồn tại trong graph."""

    def __init__(self, contract_id: int) -> None:
        self.contract_id = contract_id
        super().__init__(f"Không tìm thấy hợp đồng contract_id={contract_id}.")


class EmptyDocumentError(Exception):
    """Không tách được Điều nào từ tài liệu đầu vào."""


def _row_to_dict(r: dict) -> dict:
    return {
        "contract_id": r["contract_id"],
        "name": r["name"],
        "source_filename": r["source_filename"] or "",
        "n_clauses": r["n_clauses"],
    }


def list_contracts() -> list[dict]:
    records = get_graph().query(LIST_CONTRACTS)
    return [_row_to_dict(r) for r in records]


def get_contract(contract_id: int) -> dict:
    records = get_graph().query(GET_CONTRACT_STATUS, params={"id": contract_id})
    if not records or not records[0]["name"]:
        raise ContractNotFoundError(contract_id)
    return _row_to_dict(records[0])


def import_contract(filename: str, raw: bytes) -> dict:
    """Parse (docling nếu không phải md/txt) -> tách Điều -> LLM trích quan hệ -> build thành
    1 hợp đồng MỚI (contract_id tự tăng), không đụng tới hợp đồng đã có."""
    suffix = Path(filename).suffix.lower()
    contract_name = Path(filename).stem

    logger.info("Bắt đầu import hợp đồng, filename=%s", filename)

    if suffix in (".md", ".txt"):
        text = normalize_markdown(raw.decode("utf-8"))
    else:
        text = parse_to_markdown(filename, raw)  # đã chuẩn hoá bên trong parse_to_markdown

    sections, clauses = split_into_sections_and_clauses(text)
    if not clauses:
        logger.warning("Không tách được Điều nào từ tài liệu, filename=%s", filename)
        raise EmptyDocumentError

    extraction, extraction_usage = extract_relations(contract_name, clauses)

    contract_id = next_contract_id()
    n_cross = build_graph(contract_id, contract_name, sections, clauses, extraction, extraction_usage, source_filename=filename)

    logger.info(
        "Hoàn tất import hợp đồng, contract_id=%s, filename=%s, n_clauses=%d, n_cross=%d",
        contract_id, filename, len(clauses), n_cross,
    )

    return {
        "contract_id": contract_id,
        "name": contract_name,
        "source_filename": filename,
        "n_clauses": len(clauses),
        "n_cross": n_cross,
    }


def remove_contract(contract_id: int) -> None:
    logger.info("Bắt đầu xoá hợp đồng, contract_id=%s", contract_id)
    get_contract(contract_id)  # raise ContractNotFoundError nếu không tồn tại
    delete_contract(contract_id)
    logger.info("Hoàn tất xoá hợp đồng, contract_id=%s", contract_id)
