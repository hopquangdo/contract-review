"""6 node của LangGraph chấm 1 mục checklist, gộp vào 1 file: generate_queries -> retrieve -> rerank
-> expand -> build_context -> evaluate (xem checklist/workflow.py::build_item_graph cho cách
lắp graph, checklist/evaluator.py::ChecklistEvaluator.stream_checklist_item cho cách gọi tuần tự
KHÔNG qua LangGraph). Mỗi node là 1 hàm run_<tên node>(state) -> dict để merge vào ChecklistItemState -
tên hàm mang tiền tố vì cả 6 hàm sống chung 1 module, không thể trùng tên "run" như khi còn tách file
riêng."""

from __future__ import annotations

import json
import logging

from config.settings import QUERY_GENERATION_MODEL
from llm.usage import invoke_structured_with_usage
from rag.retrieval import Retrieval
from schema.checklist_item_state import ChecklistItemState
from schema.requirement_decomposition import RequirementDecomposition
from utils.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_REQUIREMENT_DECOMPOSITION_SYSTEM_PROMPT = load_prompt("requirement_decomposition_prompt.txt")

_evaluator = None  # lazy singleton - tránh import vòng: checklist/evaluator.py::ChecklistEvaluator
# cũng import module này (dùng cho evaluate_checklist_item_with_requirements/stream_checklist_item),
# nên KHÔNG thể import ChecklistEvaluator ở top-level của module này (import vòng khi Python load lần
# đầu).


def _get_evaluator():
    global _evaluator
    if _evaluator is None:
        from checklist.evaluator import ChecklistEvaluator

        _evaluator = ChecklistEvaluator()
    return _evaluator


def _fallback_requirements(item: dict) -> list[dict]:
    """Tạo yêu cầu dự phòng từ question/pass_criteria/violation_criteria khi LLM phân rã thất bại."""
    raw = [item["question"], item.get("pass_criteria", ""), item.get("violation_criteria", "")]
    queries = [q for q in raw if q and q.strip()]
    return [{"requirement": item["question"], "queries": queries}] if queries else []


def decompose_requirements(item: dict) -> tuple[list[dict], dict]:
    """Phân rã 1 mục checklist thành danh sách YÊU CẦU (requirement) riêng biệt, mỗi yêu cầu kèm
    truy vấn tìm kiếm của chính nó.

    Đây là NGUỒN SỰ THẬT DUY NHẤT cho "cần kiểm tra những gì", dùng chung cho cả bước retrieval
    (flatten "queries" để vector search) LẪN bước evaluate (nhận nguyên danh sách "requirement" làm
    khung xác minh, không tự phân rã lại - xem llm/checklist_evaluation.py). Trước đây 2 bước này tự
    phân rã ĐỘC LẬP (llm/query_generation.py cũ + Bước 1 trong prompt evaluate), có thể ra 2 danh
    sách khác nhau cho cùng 1 mục checklist.

    Nếu LLM lỗi hoặc trả rỗng, fallback về 1 yêu cầu duy nhất gộp question/pass_criteria/
    violation_criteria thô làm queries - không để bước retrieval bị chặn hoàn toàn chỉ vì bước phân
    rã thất bại.

    Args:
        item: Mục checklist gốc (dict, tối thiểu có "id", "question").

    Returns:
        Tuple (requirements, usage_info) - requirements là danh sách dict
        {"requirement": str, "queries": list[str]}, usage_info gồm
        input_tokens/output_tokens/cost_usd.
    """
    user_content = f"Mục checklist (JSON):\n{json.dumps(item, ensure_ascii=False, indent=2)}"
    try:
        result, usage = invoke_structured_with_usage(
            QUERY_GENERATION_MODEL, _REQUIREMENT_DECOMPOSITION_SYSTEM_PROMPT, user_content, RequirementDecomposition
        )
    except Exception:
        logger.exception("Lỗi khi phân rã yêu cầu cho item_id=%s - fallback về question/pass/violation thô", item.get("id", ""))
        return _fallback_requirements(item), {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    requirements = [
        {"requirement": r.requirement, "queries": [q for q in r.queries if q and q.strip()]}
        for r in result.requirements
        if r.requirement and r.requirement.strip()
    ]
    requirements = [r for r in requirements if r["queries"]]
    if not requirements:
        logger.warning("LLM trả về danh sách yêu cầu rỗng cho item_id=%s - fallback về question/pass/violation thô", item.get("id", ""))
        requirements = _fallback_requirements(item)
    logger.debug("Phân rã yêu cầu cho item_id=%s: %s", item.get("id", ""), requirements)
    return requirements, usage


def run_generate_queries(state: ChecklistItemState) -> dict:
    """Node 1: phân rã 1 mục checklist thành yêu cầu + truy vấn tìm kiếm.

    Tên node "generate_queries" tương ứng với "step" trong sự kiện SSE mà frontend đọc
    (services/checklist_service.py), dù trách nhiệm đã mở rộng hơn việc sinh truy vấn thuần túy (xem
    decompose_requirements).

    Args:
        state: State hiện tại của checklist item, phải có key "item" (dict mục checklist gốc,
            tối thiểu có "id").

    Returns:
        dict để merge vào state: "requirements" (danh sách yêu cầu đã phân rã, xem
        decompose_requirements) và "query_generation_usage" (chi phí LLM của bước này).
    """
    item_id = state["item"].get("id", "")
    requirements, usage = decompose_requirements(state["item"])
    logger.info("Phân rã yêu cầu xong cho item_id=%s: %s", item_id, requirements)
    return {"requirements": requirements, "query_generation_usage": usage}


def run_retrieve(state: ChecklistItemState) -> dict:
    """Node 2: vector search THÔ (chưa chọn lọc) trên các truy vấn đã sinh ở run_generate_queries -
    xem rag/retrieval.py::Retrieval.retrieve. Tách khỏi rerank (node kế tiếp) để rerank có thể chấm
    lại điểm TRƯỚC KHI áp ngưỡng chọn candidate nào giữ lại.

    Args:
        state: State hiện tại, phải có "contract_id" và "requirements" (danh sách
            {"requirement": str, "queries": list[str]} từ node generate_queries).

    Returns:
        dict để merge vào state: "raw_candidates" (candidate thô theo từng truy vấn con).
    """
    item_id = state["item"].get("id", "")
    query_texts = [q for req in state["requirements"] for q in req["queries"]]
    raw_candidates = Retrieval(state["contract_id"]).retrieve(query_texts)
    logger.info(
        "Retrieve xong cho item_id=%s, contract_id=%s, n_queries=%d",
        item_id, state["contract_id"], len(raw_candidates),
    )
    return {"raw_candidates": raw_candidates}


def run_rerank(state: ChecklistItemState) -> dict:
    """Node 3: (tuỳ chọn) chấm lại điểm candidate thô bằng cross-encoder model, rồi áp ngưỡng chọn
    candidate nào giữ lại cho từng truy vấn con - xem rag/retrieval.py::Retrieval.rerank.

    Args:
        state: State hiện tại, phải có "raw_candidates" (từ node retrieve).

    Returns:
        dict để merge vào state: "match" (điểm/Điều cha tích luỹ) và "top_numbers" (Clause đã chọn).
    """
    item_id = state["item"].get("id", "")
    match, top_numbers = Retrieval(state["contract_id"]).rerank(state["raw_candidates"])
    logger.info("Rerank xong cho item_id=%s, n_matched=%d", item_id, len(top_numbers))
    return {"match": match, "top_numbers": top_numbers}


def run_expand(state: ChecklistItemState) -> dict:
    """Node 4: mở rộng tập Clause qua quan hệ đồ thị THẬT (REFERS_TO/DEPENDS_ON/EXCEPTION_TO/
    REFERS_TO_APPENDIX/DEFINES) - xem rag/retrieval.py::Retrieval.expand.

    Args:
        state: State hiện tại, phải có "contract_id", "top_numbers" và "match" (từ node rerank).

    Returns:
        dict để merge vào state: "edges" (cạnh quan hệ đã mở rộng) và "numbers_to_load" (toàn bộ số
        hiệu Clause cần lấy chi tiết).
    """
    item_id = state["item"].get("id", "")
    edges, numbers_to_load = Retrieval(state["contract_id"]).expand(state["top_numbers"], state["match"])
    logger.info("Expand xong cho item_id=%s, n_numbers_to_load=%d", item_id, len(numbers_to_load))
    return {"edges": edges, "numbers_to_load": numbers_to_load}


def run_build_context(state: ChecklistItemState) -> dict:
    """Node 5: lắp Clause cuối cùng (chi tiết + preamble + metadata hợp đồng, gộp theo Điều cha) +
    dựng cây evidences - xem rag/retrieval.py::Retrieval.build_context.

    Args:
        state: State hiện tại, phải có "contract_id", "numbers_to_load", "top_numbers", "match",
            "edges" (từ các node retrieve/rerank/expand).

    Returns:
        dict để merge vào state: "clauses" (nhóm theo Điều cha) và "evidences" (cây quan hệ đồ thị).
    """
    item_id = state["item"].get("id", "")
    result = Retrieval(state["contract_id"]).build_context(
        state["numbers_to_load"], state["top_numbers"], state["match"], state["edges"], len(state["raw_candidates"]),
    )
    logger.info(
        "Build context xong cho item_id=%s, contract_id=%s, n_clauses=%d",
        item_id, state["contract_id"], len(result["clauses"]),
    )
    return {"clauses": result["clauses"], "evidences": result["evidences"]}


def run_evaluate(state: ChecklistItemState) -> dict:
    """Node 6: LLM đánh giá pass/fail dựa trên các Điều đã search - xem checklist/evaluator.py.

    Args:
        state: State hiện tại, phải có "item", "requirements" (từ node generate_queries) và
            "clauses" (từ node build_context).

    Returns:
        dict để merge vào state: "evaluation" (ClauseEvaluation - kết quả chấm) và "usage" (chi phí
        LLM của bước này).
    """
    item_id = state["item"].get("id", "")
    evaluation, usage = _get_evaluator().evaluate_item(state["item"], state["requirements"], state["clauses"])
    logger.info("Evaluate xong cho item_id=%s, status=%s", item_id, evaluation.status)
    return {"evaluation": evaluation, "usage": usage}
