"""Constraint và index Neo4j cho graph hợp đồng."""

from __future__ import annotations

import logging

from langchain_neo4j import Neo4jGraph

logger = logging.getLogger(__name__)

_DROP_STATEMENTS = [
    # Ràng buộc cũ (unique theo "name" trần) từ trước khi hỗ trợ nhiều hợp đồng - phải xoá vì
    # giờ đây "name" được phép trùng giữa các hợp đồng khác nhau, chỉ "uid" (có tiền tố
    # contract_id) mới cần duy nhất.
    "DROP CONSTRAINT clausetype_name IF EXISTS",
    "DROP CONSTRAINT org_name IF EXISTS",
]

_STATEMENTS = [
    "CREATE CONSTRAINT agreement_id IF NOT EXISTS FOR (a:Agreement) REQUIRE a.contract_id IS UNIQUE",
    "CREATE CONSTRAINT clause_uid IF NOT EXISTS FOR (c:Clause) REQUIRE c.uid IS UNIQUE",
    "CREATE CONSTRAINT excerpt_uid IF NOT EXISTS FOR (e:Excerpt) REQUIRE e.uid IS UNIQUE",
    "CREATE CONSTRAINT definition_uid IF NOT EXISTS FOR (d:Definition) REQUIRE d.uid IS UNIQUE",
    "CREATE CONSTRAINT clausetype_uid IF NOT EXISTS FOR (ct:ClauseType) REQUIRE ct.uid IS UNIQUE",
    "CREATE CONSTRAINT org_uid IF NOT EXISTS FOR (o:Organization) REQUIRE o.uid IS UNIQUE",
    "CREATE CONSTRAINT governinglaw_uid IF NOT EXISTS FOR (gl:GoverningLaw) REQUIRE gl.uid IS UNIQUE",
    "CREATE CONSTRAINT disputeresolution_uid IF NOT EXISTS FOR (dr:DisputeResolution) REQUIRE dr.uid IS UNIQUE",
    "CREATE INDEX clause_agreement_idx IF NOT EXISTS FOR (c:Clause) ON (c.agreement_id)",
]


def ensure_schema(graph: Neo4jGraph) -> None:
    """Tạo constraint/index nếu chưa có, xoá constraint cũ không còn phù hợp - gọi ở đầu mỗi
    lần build_graph()."""
    logger.info("Bắt đầu migration schema Neo4j (constraint/index)")
    for statement in _DROP_STATEMENTS:
        graph.query(statement)
    for statement in _STATEMENTS:
        graph.query(statement)
    logger.info("Hoàn tất migration schema Neo4j (constraint/index)")
