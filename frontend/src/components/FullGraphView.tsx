import { useCallback, useEffect, useMemo, useState } from "react";
import { applyNodeChanges, type Edge, type Node, type NodeChange } from "@xyflow/react";
import { getContractGraph } from "../api";
import type { FullGraphNodeType, FullGraphResponse } from "../types";
import FullGraphNodeComponent, { NODE_TYPE_STYLE, type FullGraphNodeData } from "./graph/FullGraphNode";
import GraphShell, { type NodeTypeOption, type RelationOption } from "./graph/GraphShell";
import { draggedNodeOverlapsAny, findNearestValidPosition } from "./graph/dragCollision";
import { NODE_HEIGHT, NODE_WIDTH, elkGraphLayout } from "./graph/elkLayout";

const nodeTypes = { fullGraphNode: FullGraphNodeComponent };

const ALL_NODE_TYPES: FullGraphNodeType[] = ["Contract", "Section", "Clause", "Appendix", "Party", "GoverningLaw", "DisputeResolution"];
const NODE_TYPE_OPTIONS: NodeTypeOption[] = ALL_NODE_TYPES.map((t) => ({ key: t, label: NODE_TYPE_STYLE[t].label, dotClass: NODE_TYPE_STYLE[t].dot }));

// Toàn bộ loại quan hệ THẬT có thể xuất hiện - khớp đúng knowledge_graph/graph_export.py (không
// bịa thêm loại quan hệ không tồn tại trong Neo4j thật).
const ALL_RELATIONS = [
  "HAS_SECTION", "HAS_CLAUSE", "HAS_PARTY", "GOVERNED_BY", "HAS_DISPUTE_RULE",
  "REFERS_TO", "DEPENDS_ON", "EXCEPTION_TO", "REFERS_TO_APPENDIX", "DEFINES",
];

const RELATION_COLOR: Record<string, string> = {
  HAS_SECTION: "#94a3b8",
  HAS_CLAUSE: "#94a3b8",
  HAS_PARTY: "#14b8a6",
  GOVERNED_BY: "#8b5cf6",
  HAS_DISPUTE_RULE: "#f43f5e",
  REFERS_TO: "#2563eb",
  DEPENDS_ON: "#7c3aed",
  EXCEPTION_TO: "#ed1c24",
  REFERS_TO_APPENDIX: "#d97706",
  DEFINES: "#059669",
};
const RELATION_OPTIONS: RelationOption[] = ALL_RELATIONS.map((r) => ({ key: r, label: r, color: RELATION_COLOR[r] }));

const DASHED_RELATIONS = new Set(["REFERS_TO", "REFERS_TO_APPENDIX", "DEFINES", "EXCEPTION_TO"]);

// Màu hex song song với NODE_TYPE_STYLE (class Tailwind) - MiniMap của React Flow cần màu CSS
// thật, không đọc được class Tailwind.
const NODE_TYPE_HEX: Record<FullGraphNodeType, string> = {
  Contract: "#ed1c24",
  Section: "#0ea5e9",
  Clause: "#10b981",
  Appendix: "#f59e0b",
  Party: "#14b8a6",
  GoverningLaw: "#8b5cf6",
  DisputeResolution: "#f43f5e",
};

interface FullGraphViewProps {
  contractId: number;
  onClose?: () => void;
  // Số hiệu Khoản được trích dẫn ở mục checklist đang chọn (xem ChecklistPanel) - node đầu tiên
  // trong danh sách này tự được chọn để highlight/hiện chi tiết, KHÔNG lọc ẩn các node khác (vẫn
  // xem được toàn bộ graph, chỉ nổi bật đúng phần liên quan tới mục đang xem).
  highlightNumbers?: string[];
}

export default function FullGraphView({ contractId, onClose, highlightNumbers }: FullGraphViewProps) {
  const [data, setData] = useState<FullGraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [layingOut, setLayingOut] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(new Set(ALL_NODE_TYPES));
  const [enabledRelations, setEnabledRelations] = useState<Set<string>>(new Set(ALL_RELATIONS));

  const [layoutEdges, setLayoutEdges] = useState<Edge[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelectedId(null);
    getContractGraph(contractId)
      .then(setData)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [contractId]);

  // Khi mục checklist đang chọn đổi (highlightNumbers đổi), tự chọn node Khoản đầu tiên được trích
  // dẫn để "NỐT ĐANG CHỌN" + viền nổi bật cập nhật theo, không cần người dùng tự bấm lại trên graph.
  useEffect(() => {
    if (highlightNumbers && highlightNumbers.length > 0) {
      setSelectedId(`clause:${highlightNumbers[0]}`);
    }
  }, [highlightNumbers]);

  const highlightIds = useMemo(() => new Set((highlightNumbers || []).map((n) => `clause:${n}`)), [highlightNumbers]);

  // ELK.js chạy bất đồng bộ (Promise) - tính lại mỗi khi đổi hợp đồng, KHÔNG chạy lại khi chỉ đổi
  // selectedId/highlight (tránh giật layout mỗi lần bấm chọn node).
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    setLayingOut(true);
    elkGraphLayout(data.nodes, data.edges)
      .then((built) => {
        if (cancelled) return;
        setLayoutEdges(built.edges);
        setNodes(built.nodes);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(`Failed to compute graph layout: ${(e as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLayingOut(false);
      });
    return () => {
      cancelled = true;
    };
  }, [data]);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)), []);

  // Thả tay kéo: nếu vị trí mới KHÔNG đè lên node nào khác thì GIỮ NGUYÊN. Nếu đè, KHÔNG nhảy hẳn về
  // vị trí ELK.js gốc - chỉ đẩy tới VỊ TRÍ HỢP LỆ GẦN NHẤT (dịch chuyển tối thiểu để thoát chồng lấn,
  // xem dragCollision.ts::findNearestValidPosition).
  const onNodeDragStop = useCallback((_: unknown, draggedNode: Node) => {
    setNodes((nds) => {
      if (!draggedNodeOverlapsAny(draggedNode, nds, NODE_WIDTH, NODE_HEIGHT)) return nds;
      const validPos = findNearestValidPosition(draggedNode, nds, NODE_WIDTH, NODE_HEIGHT);
      return nds.map((n) => (n.id === draggedNode.id ? { ...n, position: validPos } : n));
    });
  }, []);

  // Unchecking a NODE TYPE hides nodes of that type - a node is fully hidden if, after that, it has
  // no more path back to the root Contract node through the remaining containment relations
  // (HAS_SECTION/HAS_CLAUSE/HAS_PARTY/GOVERNED_BY/HAS_DISPUTE_RULE).
  //
  // Unchecking a RELATION only CUTS that relation's edges originating at the CURRENTLY SELECTED node
  // (e.g. select "Article 2" then uncheck "Contains" -> only the Article2->Clause2.1/2.2 edges are
  // cut). Cutting an edge does NOT hide its target outright - the target only disappears if it has no
  // OTHER path left to the root (e.g. a clause still reachable via a different parent's HAS_CLAUSE
  // edge stays visible even if one specific reference edge into it got cut). With no node selected,
  // unchecking a relation just hides that relation's edges everywhere, no node is hidden.
  const CONTAINMENT_RELATIONS = useMemo(() => new Set(["HAS_SECTION", "HAS_CLAUSE", "HAS_PARTY", "GOVERNED_BY", "HAS_DISPUTE_RULE"]), []);
  const visibleNodeIds = useMemo(() => {
    const typeHidden = new Set<string>();
    for (const n of nodes) {
      if (!enabledTypes.has((n.data as unknown as FullGraphNodeData).type)) typeHidden.add(n.id);
    }
    const childrenOf = new Map<string, string[]>();
    for (const e of layoutEdges) {
      const relation = (e.data as { relation: string } | undefined)?.relation || "";
      if (!CONTAINMENT_RELATIONS.has(relation)) continue;
      const cut = selectedId != null && e.source === selectedId && !enabledRelations.has(relation);
      if (cut) continue;
      if (!childrenOf.has(e.source)) childrenOf.set(e.source, []);
      childrenOf.get(e.source)!.push(e.target);
    }
    const root = nodes.find((n) => (n.data as unknown as FullGraphNodeData).type === "Contract");
    const reachable = new Set<string>();
    if (root && !typeHidden.has(root.id)) {
      reachable.add(root.id);
      const queue = [root.id];
      while (queue.length) {
        const cur = queue.shift()!;
        for (const next of childrenOf.get(cur) || []) {
          if (typeHidden.has(next) || reachable.has(next)) continue;
          reachable.add(next);
          queue.push(next);
        }
      }
    }
    return reachable;
  }, [nodes, layoutEdges, enabledTypes, enabledRelations, selectedId, CONTAINMENT_RELATIONS]);
  const visibleNodes = useMemo(
    () =>
      nodes
        .map((n) => ({ ...n, data: { ...n.data, selected: n.id === selectedId, highlighted: highlightIds.has(n.id) } }))
        .filter((n) => visibleNodeIds.has(n.id)),
    [nodes, visibleNodeIds, selectedId, highlightIds],
  );
  const visibleEdges = useMemo(
    () =>
      layoutEdges
        .filter((e) => {
          const relation = (e.data as { relation: string } | undefined)?.relation || "";
          if (!visibleNodeIds.has(e.source) || !visibleNodeIds.has(e.target)) return false;
          if (enabledRelations.has(relation)) return true;
          if (selectedId) return e.source !== selectedId;
          return false;
        })
        .map((e) => {
          const relation = (e.data as { relation: string }).relation;
          return {
            ...e,
            style: { stroke: RELATION_COLOR[relation] || "#cbd5e1", strokeDasharray: DASHED_RELATIONS.has(relation) ? "5 4" : undefined },
          };
        }),
    [layoutEdges, enabledRelations, visibleNodeIds],
  );

  const stats = useMemo(() => {
    if (!data) return [];
    const counts = new Map<FullGraphNodeType, number>();
    for (const n of data.nodes) counts.set(n.type, (counts.get(n.type) || 0) + 1);
    return ALL_NODE_TYPES.filter((t) => counts.has(t)).map((t) => ({ key: t, label: NODE_TYPE_STYLE[t].label, dotClass: NODE_TYPE_STYLE[t].dot, count: counts.get(t)! }));
  }, [data]);

  const selectedNode = data?.nodes.find((n) => n.id === selectedId) || null;

  function toggleType(key: string) {
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }
  function toggleRelation(key: string) {
    setEnabledRelations((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="flex-1 min-w-0 flex flex-col border border-border rounded-2xl bg-white overflow-hidden">
      <div className="h-[4.5rem] shrink-0 px-[1.1rem] flex items-center justify-between border-b border-border">
        <div className="min-w-0">
          <h3 className="text-[0.9rem] font-bold m-0 truncate">Full Graph</h3>
          <p className="text-[0.76rem] text-muted m-0 truncate">Explore the whole contract structure and its relations</p>
        </div>
        <div className="flex items-center gap-2">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="text-sm font-semibold text-muted hover:text-text border border-border rounded-lg px-3 py-1.5"
            >
              &larr; Back
            </button>
          )}
        </div>
      </div>

      {error ? (
        <div className="flex-1 flex items-center justify-center text-fail text-sm">{error}</div>
      ) : (
        <GraphShell
          loading={loading || layingOut}
          loadingLabel={loading ? "Loading graph..." : "Computing layout..."}
          emptyMessage="No graph data yet."
          nodes={visibleNodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={setSelectedId}
          onPaneClick={() => setSelectedId(null)}
          detailHint="Select a node on the diagram to see its details."
          detailContent={
            selectedNode && (
              <div>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${NODE_TYPE_STYLE[selectedNode.type].dot}`} />
                  <span className="font-semibold text-[0.8rem] truncate">
                    {selectedNode.number ? `${NODE_TYPE_STYLE[selectedNode.type].label} ${selectedNode.number}` : selectedNode.label}
                  </span>
                </div>
                {selectedNode.number && <p className="text-[0.76rem] text-muted m-0">{selectedNode.label}</p>}
                {selectedNode.role && <p className="text-[0.76rem] text-muted m-0">Role: {selectedNode.role}</p>}
              </div>
            )
          }
          nodeTypeOptions={NODE_TYPE_OPTIONS}
          enabledTypes={enabledTypes}
          onToggleType={toggleType}
          relationOptions={RELATION_OPTIONS}
          enabledRelations={enabledRelations}
          onToggleRelation={toggleRelation}
          stats={stats}
          totalNodes={data?.nodes.length || 0}
          totalEdges={data?.edges.length || 0}
          minimapNodeColor={(n) => NODE_TYPE_HEX[(n.data as unknown as FullGraphNodeData).type] || "#94a3b8"}
        />
      )}
    </div>
  );
}
