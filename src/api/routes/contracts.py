"""API quản lý hợp đồng: liệt kê, xem, import, xoá."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from services import contract_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("")
def list_contracts() -> dict:
    contracts = contract_service.list_contracts()
    logger.info("Liệt kê hợp đồng, n_contracts=%d", len(contracts))
    return {"contracts": contracts}


@router.get("/{contract_id}")
def get_contract(contract_id: int) -> dict:
    logger.info("Xem chi tiết hợp đồng, contract_id=%s", contract_id)
    try:
        return contract_service.get_contract(contract_id)
    except contract_service.ContractNotFoundError as e:
        logger.warning("Không tìm thấy hợp đồng, contract_id=%s", contract_id)
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("")
async def import_contract(file: UploadFile = File(...)) -> dict:
    logger.info("Bắt đầu import hợp đồng, filename=%s", file.filename)
    raw = await file.read()
    try:
        result = contract_service.import_contract(file.filename or "contract", raw)
    except contract_service.EmptyDocumentError as e:
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
    logger.info("Bắt đầu xoá hợp đồng, contract_id=%s", contract_id)
    try:
        contract_service.remove_contract(contract_id)
    except contract_service.ContractNotFoundError as e:
        logger.warning("Không tìm thấy hợp đồng để xoá, contract_id=%s", contract_id)
        raise HTTPException(status_code=404, detail=str(e)) from e
    logger.info("Hoàn tất xoá hợp đồng, contract_id=%s", contract_id)
    return {"deleted": contract_id}
