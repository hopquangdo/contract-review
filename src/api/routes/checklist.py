"""API đánh giá checklist trên 1 hợp đồng."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from services import checklist_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checklist"])


@router.post("/checklist-item")
def checklist_item(payload: dict) -> dict:
    contract_id = payload.get("contract_id")
    logger.info("Bắt đầu đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)
    try:
        result = checklist_service.evaluate_single_item(
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
    """Server-Sent Events (SSE) - phát ra từng bước (generate_queries/retrieval/evaluate) ngay khi
    xong, thay vì đợi cả pipeline xong mới trả 1 lần như /checklist-item. Mỗi event là 1 dòng
    "data: {json}\\n\\n" - xem services/checklist_service.py::stream_single_item()."""
    contract_id = payload.get("contract_id")
    logger.info("Bắt đầu STREAM đánh giá 1 mục checklist đơn lẻ, contract_id=%s", contract_id)

    def event_stream():
        try:
            for event in checklist_service.stream_single_item(
                contract_id=payload["contract_id"],
                question=payload["question"],
                pass_criteria=payload.get("pass_criteria", ""),
                violation_criteria=payload.get("violation_criteria", ""),
                note=payload.get("note", ""),
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Lỗi khi STREAM đánh giá mục checklist đơn lẻ, contract_id=%s", contract_id)
            yield f"data: {json.dumps({'step': 'error', 'message': 'Đã xảy ra lỗi khi xử lý yêu cầu.'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/checklist")
async def checklist(contract_id: int = Form(...), file: UploadFile = File(...)) -> dict:
    logger.info("Bắt đầu chấm checklist hàng loạt, contract_id=%s, file=%s", contract_id, file.filename)
    data = json.loads((await file.read()).decode("utf-8"))
    try:
        evaluations = checklist_service.evaluate_checklist_batch(contract_id, data["items"])
    except Exception:
        logger.exception("Lỗi khi chấm checklist hàng loạt, contract_id=%s", contract_id)
        raise
    logger.info(
        "Hoàn tất chấm checklist hàng loạt, contract_id=%s, checklist_name=%s, n_items=%d",
        contract_id, data["name"], len(evaluations),
    )
    return {"checklist_name": data["name"], "evaluations": evaluations}
