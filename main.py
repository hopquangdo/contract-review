"""Ứng dụng FastAPI cung cấp các API phục vụ các chức năng của hệ thống.

Chạy cục bộ (cần Neo4j + biến môi trường trong .env, xem .env.example):
    uvicorn main:app --reload --port 8000
Frontend (frontend/index.html) gọi vào http://127.0.0.1:8000 - là static HTML/JS thuần, không
cần build, chạy bằng 1 trong 2 cách:
    - Mở thẳng frontend/index.html bằng trình duyệt.
    - Serve qua HTTP: cd frontend && python -m http.server 5500 (rồi mở http://localhost:5500)

Chạy bằng Docker Compose (dựng cả Neo4j + API + frontend):
    docker compose up --build
API: http://localhost:8000 - Frontend: http://localhost:5500 - Neo4j Browser: http://localhost:7475
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from config.logging_config import setup_logging  # noqa: E402

setup_logging()

import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.routes import checklist, contracts  # noqa: E402
from config.settings import EVALUATOR_MODEL, GRAPH_EXTRACTION_MODEL, QUERY_GENERATION_MODEL  # noqa: E402
from knowledge_graph.client import get_graph  # noqa: E402
from llm.client import get_chat_model  # noqa: E402
from llm.embeddings import get_embeddings  # noqa: E402
from knowledge_graph.graph import Graph  # noqa: E402

logger = logging.getLogger(__name__)
_graph = Graph()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi tạo sẵn kết nối Neo4j và các client LLM/embedding lúc app start, đóng driver Neo4j lúc app tắt.

    Warm-up trước nhằm tránh request đầu tiên của người dùng phải chờ khởi tạo.

    Args:
        app: Instance FastAPI đang được khởi động (không dùng trực tiếp, bắt buộc theo
            chữ ký contextmanager của FastAPI lifespan).
    """
    get_graph()
    for model in {GRAPH_EXTRACTION_MODEL, QUERY_GENERATION_MODEL, EVALUATOR_MODEL}:
        get_chat_model(model)
    get_embeddings()
    try:
        _graph.get_vector_store()
    except Exception:
        # Index "excerpt_embedding" chỉ được tạo khi Graph.build_graph() chạy lần đầu (xem
        # knowledge_graph/graph.py) - trên Neo4j còn trống (chưa import hợp đồng nào), index chưa tồn
        # tại nên bước warm-up này có thể lỗi; không chặn app khởi động vì retrieval chỉ thực
        # sự cần vector store sau khi đã có ít nhất 1 hợp đồng.
        logger.warning(
            "Không khởi tạo trước được Neo4jVector (có thể do chưa có hợp đồng nào / index chưa tồn tại)",
            exc_info=True,
        )

    yield

    get_graph().close()


app = FastAPI(title="Contract GraphRAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contracts.router)
app.include_router(checklist.router)
