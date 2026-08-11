"""LangGraph cho luồng chấm 1 mục checklist - 3 node tách bạch:

generate_queries -> retrieval -> evaluate

Mỗi node là 1 module riêng trong rag/nodes/ (xem rag/state.py cho state dùng chung) - thêm node
mới (vd 1 bước "verify evidence" sau evaluate) chỉ cần viết thêm 1 file trong rag/nodes/ rồi nối
vào graph ở đây, không phải sửa các node đã có."""

from __future__ import annotations

import logging
import time
from typing import Iterator

from langgraph.graph import END, StateGraph

from llm.checklist_evaluation import ClauseEvaluation
from llm.usage import sum_usage
from rag.nodes import evaluate, generate_queries, retrieval
from rag.state import ChecklistItemState

logger = logging.getLogger(__name__)


def _build_item_graph():
    graph = StateGraph(ChecklistItemState)
    graph.add_node("generate_queries", generate_queries.run)
    graph.add_node("retrieval", retrieval.run)
    graph.add_node("evaluate", evaluate.run)
    graph.set_entry_point("generate_queries")
    graph.add_edge("generate_queries", "retrieval")
    graph.add_edge("retrieval", "evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile()


_item_graph = _build_item_graph()


def evaluate_checklist_item(contract_id: int, item: dict) -> tuple[ClauseEvaluation, list[dict], dict]:
    """Chạy graph generate_queries->retrieval->evaluate cho 1 mục checklist. Trả về (evaluation,
    clauses đã truy hồi, usage_info - usage_info là TỔNG chi phí cả 2 lệnh LLM trong luồng
    (generate_queries + evaluate), gộp bằng llm.usage.sum_usage - không chỉ riêng bước evaluate
    như trước, vì thêm bước generate_queries cũng tốn 1 lệnh LLM thật, bỏ sót sẽ báo thiếu chi phí
    cho người dùng."""
    logger.debug("Bắt đầu luồng generate_queries->retrieval->evaluate cho item_id=%s, contract_id=%s", item.get("id", ""), contract_id)
    start = time.perf_counter()
    final_state = _item_graph.invoke(
        {
            "contract_id": contract_id, "item": item, "query_texts": [], "clauses": [],
            "evaluation": None, "query_generation_usage": None, "usage": None,
        }
    )
    total_usage = sum_usage(final_state["query_generation_usage"], final_state["usage"])
    total_usage["duration_seconds"] = round(time.perf_counter() - start, 2)
    return final_state["evaluation"], final_state["clauses"], total_usage


def stream_checklist_item(contract_id: int, item: dict) -> Iterator[tuple[str, dict]]:
    """Giống evaluate_checklist_item() nhưng trả về generator (node_name, partial_state) - phát ra
    NGAY khi từng node chạy xong (LangGraph stream_mode="updates"), dùng cho API streaming (SSE) để
    frontend hiển thị tiến trình thời gian thực thay vì đợi cả 3 node chạy xong mới có phản hồi."""
    logger.debug(
        "Bắt đầu STREAM luồng generate_queries->retrieval->evaluate cho item_id=%s, contract_id=%s",
        item.get("id", ""), contract_id,
    )
    initial_state = {
        "contract_id": contract_id, "item": item, "query_texts": [], "clauses": [],
        "evaluation": None, "query_generation_usage": None, "usage": None,
    }
    start = time.perf_counter()
    for update in _item_graph.stream(initial_state, stream_mode="updates"):
        # update dạng {"<node_name>": {<field thay đổi bởi node đó>}} - đúng 1 cặp key/value mỗi
        # lần vì các node chạy tuần tự (không có nhánh song song trong graph này).
        for node_name, partial_state in update.items():
            if node_name == "evaluate":
                # Node cuối cùng - gắn tổng thời gian CẢ pipeline (từ generate_queries tới đây)
                # vào đây để checklist_service.stream_single_item() đính kèm vào event cuối.
                partial_state = {**partial_state, "duration_seconds": round(time.perf_counter() - start, 2)}
            yield node_name, partial_state
