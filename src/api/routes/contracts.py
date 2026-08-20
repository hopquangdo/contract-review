"""API quản lý hợp đồng: liệt kê, xem, import, xoá."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from services.contract_service import ContractNotFoundError, ContractService, EmptyDocumentError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contracts", tags=["contracts"])
_contract_service = ContractService()


@router.get("")
def list_contracts() -> dict:
    """Liệt kê toàn bộ hợp đồng hiện có trong graph.

    Returns:
        dict với key "contracts" (danh sách hợp đồng, xem
        services.contract_service.ContractService.list_contracts()).
    """
    contracts = _contract_service.list_contracts()
    logger.info("Liệt kê hợp đồng, n_contracts=%d", len(contracts))
    return {"contracts": contracts}


@router.get("/{contract_id}")
def get_contract(contract_id: int) -> dict:
    """Xem thông tin chi tiết của 1 hợp đồng.

    Args:
        contract_id: ID hợp đồng cần xem.

    Returns:
        dict thông tin hợp đồng, xem services.contract_service.ContractService.get_contract().

    Raises:
        HTTPException: 404 nếu không tìm thấy hợp đồng.
    """
    logger.info("Xem chi tiết hợp đồng, contract_id=%s", contract_id)
    try:
        return _contract_service.get_contract(contract_id)
    except ContractNotFoundError as e:
        logger.warning("Không tìm thấy hợp đồng, contract_id=%s", contract_id)
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{contract_id}/graph")
def get_contract_graph(contract_id: int) -> dict:
    """Xem TOÀN BỘ cấu trúc graph tri thức của 1 hợp đồng (Agreement/Section/Clause/Phụ lục/Party/
    GoverningLaw/DisputeResolution + mọi quan hệ) - dùng cho trang "Full Graph" frontend, khác
    /api/similar-clauses (chỉ evidences theo 1 câu hỏi cụ thể).

    Args:
        contract_id: ID hợp đồng cần xem.

    Returns:
        dict {"contract_id", "contract_name", "nodes", "edges"}, xem
        services.contract_service.ContractService.get_contract_graph().

    Raises:
        HTTPException: 404 nếu không tìm thấy hợp đồng.
    """
    logger.info("Xem full graph hợp đồng, contract_id=%s", contract_id)
    try:
        return _contract_service.get_contract_graph(contract_id)
    except ContractNotFoundError as e:
        logger.warning("Không tìm thấy hợp đồng, contract_id=%s", contract_id)
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("")
async def import_contract(file: UploadFile = File(...)) -> dict:
    """Import 1 hợp đồng mới từ file tải lên.

    Args:
        file: File hợp đồng (docx/pdf/md/txt, ...).

    Returns:
        dict kết quả import, xem services.contract_service.ContractService.import_contract().

    Raises:
        HTTPException: 422 nếu không tách được Điều nào từ tài liệu.
    """
    logger.info("Bắt đầu import hợp đồng, filename=%s", file.filename)
    raw = await file.read()
    try:
        result = _contract_service.import_contract(file.filename or "contract", raw)
    except EmptyDocumentError as e:
        logger.warning("Không tách được Điều nào từ tài liệu, filename=%s", file.filename)
        raise HTTPException(status_code=422, detail="Không tách được Điều nào từ tài liệu này.") from e
    except Exception:
        logger.exception("Lỗi khi import hợp đồng, filename=%s", file.filename)
        raise
    logger.info(
        "Hoàn tất import hợp đồng, contract_id=%s, filename=%s, n_clauses=%s",
        result.get("contract_id"), file.filename, result.get("n_clauses"),
    )
    return result


@router.delete("/{contract_id}")
def remove_contract(contract_id: int) -> dict:
    """Xoá 1 hợp đồng khỏi graph.

    Args:
        contract_id: ID hợp đồng cần xoá.

    Returns:
        dict với key "deleted" là contract_id vừa xoá.

    Raises:
        HTTPException: 404 nếu không tìm thấy hợp đồng.
    """
    logger.info("Bắt đầu xoá hợp đồng, contract_id=%s", contract_id)
    try:
        _contract_service.remove_contract(contract_id)
    except ContractNotFoundError as e:
        logger.warning("Không tìm thấy hợp đồng để xoá, contract_id=%s", contract_id)
        raise HTTPException(status_code=404, detail=str(e)) from e
    logger.info("Hoàn tất xoá hợp đồng, contract_id=%s", contract_id)
    return {"deleted": contract_id}
