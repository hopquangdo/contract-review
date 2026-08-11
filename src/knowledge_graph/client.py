"""Kết nối Neo4j dùng chung (langchain_neo4j) - 1 instance duy nhất cho toàn bộ ứng dụng."""

from __future__ import annotations

import logging

from langchain_neo4j import Neo4jGraph

from config.settings import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USERNAME

logger = logging.getLogger(__name__)

_graph: Neo4jGraph | None = None


def get_graph() -> Neo4jGraph:
    global _graph
    if _graph is None:
        logger.info("Khởi tạo Neo4jGraph, uri=%s, user=%s", NEO4J_URI, NEO4J_USERNAME)
        _graph = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USERNAME, password=NEO4J_PASSWORD, refresh_schema=False)
    return _graph
