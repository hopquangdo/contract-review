"""Chạy THẬT 1 checklist qua pipeline đầy đủ (generate_queries -> retrieval -> evaluate, tốn LLM
call thật), ghi kết quả (status/evidence/reasoning + evidences - cây quan hệ đồ thị) ra 1 file JSON
trong data/output/eval/ - mở file index.html Ở GỐC REPO (cùng cấp thư mục data/), chọn file JSON
này qua nút Upload để xem trực quan - KHÔNG nhúng cố định data vào HTML (viewer là 1 file HTML TĨNH
dùng chung cho mọi lần chạy, chỉ đổi file JSON upload).

Usage: python scripts/build_evidence_graph_export.py --contract-id 1 --checklist data/benchmark/bm01_checklist_input.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from knowledge_graph.client import get_graph  # noqa: E402
from checklist.evaluator import ChecklistEvaluator  # noqa: E402

logger = logging.getLogger(__name__)

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
_OUTPUT_DIR = _ROOT / "data" / "output" / "eval"
_evaluator = ChecklistEvaluator()


def _contract_name(contract_id: int) -> str:
    rows = get_graph().query("MATCH (a:Agreement {contract_id: $id}) RETURN a.name AS name", params={"id": contract_id})
    return rows[0]["name"] if rows else str(contract_id)


def run_checklist(contract_id: int, checklist: dict) -> dict:
    """Chạy MỌI mục checklist qua pipeline thật (tuần tự, không song song - để log rõ ràng theo
    thứ tự), thu thập status/evidence/reasoning + evidences (cây quan hệ đồ thị) cho từng mục."""
    items_out = []
    total = len(checklist["items"])
    for i, item in enumerate(checklist["items"], 1):
        logger.info("[%d/%d] Đang chấm '%s' (item_id=%s)...", i, total, item["question"], item.get("id"))
        evaluation, _clauses, evidences, usage = _evaluator.evaluate_checklist_item(contract_id, item)
        logger.info(
            "[%d/%d] -> status=%s, n_evidences=%d, cost=$%.4f",
            i, total, evaluation.status, len(evidences), usage.get("cost_usd") or 0,
        )
        items_out.append({
            "item_id": item.get("id", ""),
            "category": item.get("category", ""),
            "question": item["question"],
            # 3 tiêu chí GỐC của mục checklist (không phải do LLM sinh ra) - đính kèm để đối chiếu
            # trực tiếp với evidence/reasoning LLM trả về, xem index.html.
            "pass_criteria": item.get("pass_criteria", ""),
            "violation_criteria": item.get("violation_criteria", ""),
            "note": item.get("note", ""),
            "status": evaluation.status,
            "evidence": evaluation.evidence,
            "reasoning": evaluation.reason,
            "recommendation": evaluation.proposal,
            "evidences": evidences,
        })

    return {
        "contract_id": contract_id,
        "contract_name": _contract_name(contract_id),
        "checklist_name": checklist.get("name", ""),
        "items": items_out,
    }


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-id", type=int, required=True)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None, help="Mặc định: data/output/eval/evidence_graph_contract<id>.json")
    args = parser.parse_args()

    checklist = json.loads(args.checklist.read_text(encoding="utf-8"))
    data = run_checklist(args.contract_id, checklist)

    json_path = args.out or (_OUTPUT_DIR / f"evidence_graph_contract{args.contract_id}.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Đã ghi '%s' (%.0f KB, %d mục checklist) - mở data/output/eval/index.html rồi upload file này để xem.",
        json_path, json_path.stat().st_size / 1024, len(data["items"]),
    )


if __name__ == "__main__":
    main()
