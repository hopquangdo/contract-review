"""API đánh giá checklist trên 1 hợp đồng.

Có 3 endpoint: đánh giá 1 mục đơn lẻ (đồng bộ), chấm cả 1 checklist (nhiều mục) theo batch, và tìm
Điều khoản tương tự ở hợp đồng khác (tham khảo chỉnh sửa).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from rag.retrieval import ClauseNotFoundError
from services.checklist_service import ChecklistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checklist"])
_checklist_service = ChecklistService()


@router.post("/checklist-item")
def checklist_item(payload: dict) -> dict:
    """Đánh giá 1 mục checklist tuỳ ý (không thuộc checklist đã lưu) trên 1 hợp đồng.

    Args:
        payload: Dict JSON của request, gồm "contract_id" (bắt buộc), "question" (bắt buộc),
            "pass_criteria", "violation_criteria", "note" (tuỳ chọn).

    Returns:
        dict kết quả đánh giá, xem services.checklist_service.ChecklistService.evaluate_single_item().
    """
    contract_id = payload.get("contract_id")
    logger.info("Bắt đầu đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)
    try:
        result = _checklist_service.evaluate_single_item(
            contract_id=payload["contract_id"],
            question=payload["question"],
            pass_criteria=payload.get("pass_criteria", ""),
            violation_criteria=payload.get("violation_criteria", ""),
            note=payload.get("note", ""),
        )
    except Exception:
        logger.exception("Lỗi khi đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
        raise
    logger.info("Hoàn tất đánh giá mục checklist đơn lẻ, contract_id=%s, status=%s", contract_id, result.get("status"))
    return result


@router.post("/checklist-item/stream")
def checklist_item_stream(payload: dict) -> StreamingResponse:
    """Giống /checklist-item nhưng trả Server-Sent Events, phát từng bước (generate_queries/
    retrieval/evaluate) ngay khi backend xong, để UI hiện tiến trình trực tiếp thay vì phải đợi
    toàn bộ pipeline (thường vài chục giây) mới thấy phản hồi đầu tiên.

    Args:
        payload: Dict JSON của request, cùng field như /checklist-item ("contract_id", "question"
            bắt buộc; "pass_criteria", "violation_criteria", "note" tuỳ chọn).

    Returns:
        StreamingResponse media_type "text/event-stream", mỗi sự kiện 1 dòng "data: <json>\\n\\n"
        (xem services.checklist_service.ChecklistService.stream_single_item() cho các dạng sự kiện).
    """
    contract_id = payload.get("contract_id")
    logger.info("Bắt đầu stream đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)

    def event_source():
        for event in _checklist_service.stream_single_item(
            contract_id=payload["contract_id"],
            question=payload["question"],
            pass_criteria=payload.get("pass_criteria", ""),
            violation_criteria=payload.get("violation_criteria", ""),
            note=payload.get("note", ""),
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.post("/checklist")
async def checklist(contract_id: int = Form(...), file: UploadFile = File(...)) -> dict:
    """Chấm toàn bộ 1 checklist (file JSON gồm nhiều mục) trên 1 hợp đồng.

    Args:
        contract_id: ID hợp đồng cần chấm.
        file: File JSON chứa checklist, có field "name" và "items" (danh sách mục checklist).

    Returns:
        dict gồm "checklist_name" và "evaluations" (kết quả từng mục, xem
        services.checklist_service.ChecklistService.evaluate_checklist_batch()).
    """
    logger.info("Bắt đầu chấm checklist hàng loạt, contract_id=%s, file=%s", contract_id, file.filename)
    data = json.loads((await file.read()).decode("utf-8"))
    try:
        evaluations = _checklist_service.evaluate_checklist_batch(contract_id, data["items"])
    except Exception:
        logger.exception("Lỗi khi chấm checklist hàng loạt, contract_id=%s", contract_id)
        raise
    logger.info(
        "Hoàn tất chấm checklist hàng loạt, contract_id=%s, checklist_name=%s, n_items=%d",
        contract_id, data["name"], len(evaluations),
    )
    return {"checklist_name": data["name"], "evaluations": evaluations}


@router.get("/similar-clauses")
def similar_clauses(contract_id: int, clause_number: str, top_k: int = 5, same_type_only: bool = True) -> dict:
    """Tìm các Điều khoản tương tự nội dung ở các hợp đồng KHÁC hợp đồng nguồn, để reviewer tham
    khảo chỉnh sửa lại 1 Điều khoản (vd sau khi bị chấm "Không đạt" 1 mục checklist).

    Args:
        contract_id: ID hợp đồng chứa Điều khoản nguồn.
        clause_number: Số hiệu Điều khoản nguồn (vd 1 trong "cited_clauses[].number" trả về từ
            /api/checklist hoặc /api/checklist-item).
        top_k: Số lượng kết quả tối đa.
        same_type_only: True thì chỉ xét Điều khoản cùng loại (ClauseType) với Điều khoản nguồn.

    Returns:
        dict {"clauses": [...]}, xem services.checklist_service.ChecklistService.get_similar_clauses().
    """
    logger.info(
        "Bắt đầu tìm Clause tương tự, contract_id=%s, clause_number=%s", contract_id, clause_number
    )
    try:
        clauses = _checklist_service.get_similar_clauses(contract_id, clause_number, top_k, same_type_only)
    except ClauseNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        logger.exception(
            "Lỗi khi tìm Clause tương tự, contract_id=%s, clause_number=%s", contract_id, clause_number
        )
        raise
    logger.info(
        "Hoàn tất tìm Clause tương tự, contract_id=%s, clause_number=%s, n_found=%d",
        contract_id, clause_number, len(clauses),
    )
    return {"clauses": clauses}
