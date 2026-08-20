"""Nghiệp vụ quản lý hợp đồng: import, liệt kê, xem, xoá."""

from __future__ import annotations

import logging
from pathlib import Path

from ingestion.docling_parser import parse_to_markdown
from ingestion.section_splitter import split_into_sections_and_clauses
from knowledge_graph.client import get_graph
from knowledge_graph.queries import GET_CONTRACT_STATUS, LIST_CONTRACTS
from knowledge_graph.graph import Graph
from utils.text_cleanup import normalize_markdown

logger = logging.getLogger(__name__)


class ContractNotFoundError(Exception):
    """Báo hiệu hợp đồng được yêu cầu không tồn tại trong graph."""

    def __init__(self, contract_id: int) -> None:
        self.contract_id = contract_id
        super().__init__(f"Không tìm thấy hợp đồng contract_id={contract_id}.")


class EmptyDocumentError(Exception):
    """Không tách được Điều nào từ tài liệu đầu vào."""


class ContractService:
    """Nghiệp vụ quản lý hợp đồng: import, liệt kê, xem, xoá - dùng Graph cho mọi giao tiếp
    Neo4j."""

    def __init__(self) -> None:
        self._graph = Graph()

    def list_contracts(self) -> list[dict]:
        """Liệt kê toàn bộ hợp đồng hiện có trong graph.

        Returns:
            Danh sách dict thông tin hợp đồng (contract_id, name, source_filename, n_clauses).
        """
        records = get_graph().query(LIST_CONTRACTS)
        return [self._row_to_dict(r) for r in records]

    def get_contract(self, contract_id: int) -> dict:
        """Xem thông tin chi tiết của 1 hợp đồng.

        Args:
            contract_id: ID hợp đồng cần xem.

        Returns:
            dict thông tin hợp đồng (contract_id, name, source_filename, n_clauses).

        Raises:
            ContractNotFoundError: Nếu không tìm thấy hợp đồng với contract_id này.
        """
        records = get_graph().query(GET_CONTRACT_STATUS, params={"id": contract_id})
        if not records or not records[0]["name"]:
            raise ContractNotFoundError(contract_id)
        return self._row_to_dict(records[0])

    def import_contract(self, filename: str, raw: bytes) -> dict:
        """Import 1 hợp đồng mới từ nội dung file thô.

        Luồng xử lý: parse (docling nếu không phải md/txt) -> tách Điều -> LLM trích quan hệ ->
        build thành 1 hợp đồng MỚI (contract_id tự tăng), không đụng tới hợp đồng đã có.

        Args:
            filename: Tên file gốc, dùng để suy ra định dạng (suffix) và tên hợp đồng (stem).
            raw: Nội dung file dạng bytes.

        Returns:
            dict gồm contract_id, name, source_filename, n_clauses (số Điều tách được),
            n_cross (số quan hệ tham chiếu chéo LLM trích ra).

        Raises:
            EmptyDocumentError: Nếu không tách được Điều nào từ tài liệu.
        """
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

        extraction, extraction_usage = self._graph.extract_relations(contract_name, clauses)

        contract_id = self._graph.next_contract_id()
        n_cross = self._graph.build_graph(
            contract_id, contract_name, sections, clauses, extraction, extraction_usage, source_filename=filename
        )

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

    def get_contract_graph(self, contract_id: int) -> dict:
        """Xem TOÀN BỘ cấu trúc graph tri thức của 1 hợp đồng (dùng cho trang "Full Graph" frontend).

        Args:
            contract_id: ID hợp đồng cần xem.

        Returns:
            dict {"contract_id", "contract_name", "nodes", "edges"}, xem
            knowledge_graph.graph.Graph.export_contract_graph().

        Raises:
            ContractNotFoundError: Nếu không tìm thấy hợp đồng với contract_id này.
        """
        data = self._graph.export_contract_graph(contract_id)
        if not data["contract_name"]:
            raise ContractNotFoundError(contract_id)
        return data

    def remove_contract(self, contract_id: int) -> None:
        """Xoá 1 hợp đồng khỏi graph.

        Args:
            contract_id: ID hợp đồng cần xoá.

        Raises:
            ContractNotFoundError: Nếu không tìm thấy hợp đồng với contract_id này.
        """
        logger.info("Bắt đầu xoá hợp đồng, contract_id=%s", contract_id)
        self.get_contract(contract_id)  # raise ContractNotFoundError nếu không tồn tại
        self._graph.delete_contract(contract_id)
        logger.info("Hoàn tất xoá hợp đồng, contract_id=%s", contract_id)

    @staticmethod
    def _row_to_dict(r: dict) -> dict:
        """Chuẩn hoá 1 record trả về từ Neo4j thành dict thông tin hợp đồng cho API."""
        return {
            "contract_id": r["contract_id"],
            "name": r["name"],
            "source_filename": r["source_filename"] or "",
            "n_clauses": r["n_clauses"],
        }
