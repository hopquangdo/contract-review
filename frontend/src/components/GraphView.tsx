import { useCallback, useEffect, useMemo, useState } from "react";
import { applyNodeChanges, type Edge, type Node, type NodeChange } from "@xyflow/react";
import { marked } from "marked";
import type { Evidence, EvidenceNode } from "../types";
import EvidenceFlowNode, { type EvidenceFlowNodeData } from "./graph/EvidenceFlowNode";
import GraphShell, { type NodeTypeOption, type RelationOption, type StatRow } from "./graph/GraphShell";
import { draggedNodeOverlapsAny, findNearestValidPosition } from "./graph/dragCollision";
import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from "./graph/layout";

// 5 loại quan hệ THẬT có thể xuất hiện trong cạnh evidences - khớp đúng
// checklist/pipeline/nodes/expand.py (REFERS_TO/DEPENDS_ON/EXCEPTION_TO/REFERS_TO_APPENDIX) +
// knowledge_graph/services/graph_expansion.py::expand_by_definitions (DEFINES, luôn mở rộng không
// điều kiện để giải thích thuật ngữ Clause đang dùng). Nhãn ghi tiếng Anh - khớp tên quan hệ Neo4j
// thật (REFERS_TO/DEPENDS_ON/...) thay vì dịch, tránh lệch nghĩa giữa UI và dữ liệu gốc.
const RELATION_LABEL: Record<string, string> = {
  REFERS_TO: "References",
  DEPENDS_ON: "Depends on",
  EXCEPTION_TO: "Exception to",
  REFERS_TO_APPENDIX: "Appendix ref",
  DEFINES: "Defines",
  CONTAINS: "Contains",
};
const ALL_RELATIONS = ["CONTAINS", "REFERS_TO", "DEPENDS_ON", "EXCEPTION_TO", "REFERS_TO_APPENDIX", "DEFINES"];

// Tông màu đỏ (--color-accent #ed1c24 của app) là màu NHẤN chính, dành cho node/cạnh quan trọng
// nhất (Khoản khớp trực tiếp câu hỏi) - các loại quan hệ khác dùng màu trung tính để không cạnh
// tranh sự chú ý với màu nhấn.
const ACCENT = "#ed1c24";
const RELATION_COLOR: Record<string, string> = {
  REFERS_TO: "#2563eb",
  DEPENDS_ON: "#7c3aed",
  EXCEPTION_TO: ACCENT,
  REFERS_TO_APPENDIX: "#d97706",
  DEFINES: "#059669",
  CONTAINS: "#cbd5e1",
};
const RELATION_OPTIONS: RelationOption[] = ALL_RELATIONS.map((r) => ({ key: r, label: RELATION_LABEL[r] || r, color: RELATION_COLOR[r] }));

const DASHED_RELATIONS = new Set(["REFERS_TO", "REFERS_TO_APPENDIX", "DEFINES"]);
const AGREEMENT_ID = "agreement";

const nodeTypes = { evidence: EvidenceFlowNode };

// "kind" của EvidenceFlowNodeData - dùng làm "Loại nốt" filter, tương tự FullGraphNodeType bên
// FullGraphView để 2 trang có cùng 1 kiểu sidebar (xem GraphShell.tsx).
const KIND_OPTIONS: NodeTypeOption[] = [
  { key: "agreement", label: "Contract", dotClass: "bg-accent" },
  { key: "article", label: "Article", dotClass: "bg-indigo-500" },
  { key: "clause-matched", label: "Direct match clause", dotClass: "bg-accent" },
  { key: "clause-context", label: "Related clause", dotClass: "bg-sky-500" },
  { key: "appendix", label: "Appendix", dotClass: "bg-amber-500" },
];

function kindKey(data: EvidenceFlowNodeData): string {
  if (data.kind === "agreement") return "agreement";
  if (data.kind === "article") return "article";
  if (data.isAppendix) return "appendix";
  return data.matched ? "clause-matched" : "clause-context";
}

interface FlatNode {
  id: string;
  data: EvidenceNode; // node cây evidences gốc, dùng lại nguyên vẹn cho panel chi tiết
}

// Suy ra số hiệu cha trực tiếp từ số hiệu con theo quy ước đánh số phân cấp thật của hệ thống (vd
// "11.2" -> cha "11", "PL02.5" -> cha "PL02") - xem ingestion/section_splitter.py. Số hiệu không có
// dấu "." (vd "9" hoặc "PL02") coi như thuộc thẳng Hợp đồng gốc, không còn cha trung gian.
function parentNumber(number: string): string | null {
  const idx = number.lastIndexOf(".");
  return idx === -1 ? null : number.slice(0, idx);
}

// Gộp TOÀN BỘ cây evidences (có thể nhiều root trùng lặp node - vd Khoản định nghĩa thuật ngữ "1.2"
// xuất hiện lại ở nhiều root) thành 1 graph DUY NHẤT, rồi truy ngược mọi node tới tận Hợp đồng gốc
// qua số hiệu cha (parentNumber) - khớp đúng yêu cầu "graph phải truy hết về nút cha", không dừng ở
// các nhánh tham chiếu chéo rời rạc như trước.
function buildUnifiedGraph(evidences: Evidence[], contractName: string): { nodes: Node[]; edges: Edge[]; flatNodes: Map<string, FlatNode> } {
  const flatNodes = new Map<string, FlatNode>();
  const crossEdges = new Map<string, { source: string; target: string; relation: string }>();

  function mergeNode(n: EvidenceNode) {
    const existing = flatNodes.get(n.number);
    // Cùng 1 số hiệu có thể xuất hiện ở nhiều nhánh với "matched"/"content" khác nhau (vd node
    // context ở nhánh này nhưng lại là root matched ở nhánh khác) - giữ bản "đầy đủ" nhất.
    if (!existing || (n.matched && !existing.data.matched) || (n.content && !existing.data.content)) {
      flatNodes.set(n.number, { id: n.number, data: n });
    }
  }

  function walk(n: EvidenceNode) {
    mergeNode(n);
    for (const child of n.children || []) {
      const relation = child.relation || "REFERS_TO";
      crossEdges.set(`${n.number}->${child.number}`, { source: n.number, target: child.number, relation });
      walk(child);
    }
  }

  // "root" của Evidence KHÔNG có field "children" - danh sách con thật nằm ở "chain" (field anh em
  // với "root", xem rag/context/citation.py::build_evidences) - phải nối "root -> mỗi phần tử
  // chain" thủ công trước khi đệ quy walk() tiếp các cấp sâu hơn (chain[i].children mới dùng đúng
  // shape đệ quy bình thường).
  for (const ev of evidences) {
    mergeNode(ev.root);
    for (const child of ev.chain) {
      const relation = child.relation || "REFERS_TO";
      crossEdges.set(`${ev.root.number}->${child.number}`, { source: ev.root.number, target: child.number, relation });
      walk(child);
    }
  }

  // Truy ngược từng node tới Hợp đồng gốc, tự sinh "stub" cho Điều/Phụ lục cha nếu chưa có trong
  // evidences (chỉ biết số hiệu, chưa biết title/content - đánh dấu isStub để phân biệt trực quan).
  const containsEdges: { source: string; target: string }[] = [];
  const seenAncestors = new Set<string>();
  for (const number of Array.from(flatNodes.keys())) {
    let current = number;
    while (true) {
      const parent = parentNumber(current);
      const parentId = parent ?? AGREEMENT_ID;
      const edgeKey = `${parentId}->${current}`;
      if (!seenAncestors.has(edgeKey)) {
        seenAncestors.add(edgeKey);
        containsEdges.push({ source: parentId, target: current });
      }
      if (parent === null) break;
      if (!flatNodes.has(parent)) {
        flatNodes.set(parent, {
          id: parent,
          data: { number: parent, title: "", is_appendix: parent.startsWith("PL"), matched: false, score: null, content: "", children: [] },
        });
      }
      if (seenAncestors.has(`${parentNumber(parent) ?? AGREEMENT_ID}->${parent}`)) break; // đã nối lên tới đây ở lượt trước
      current = parent;
    }
  }

  // Node "Điều" (số hiệu không dấu ".") vốn chỉ là stub suy ra từ số hiệu (không có content thật) -
  // tổng hợp nội dung TOÀN BỘ Khoản con của Điều đó (đã có sẵn trong flatNodes, không gọi thêm API)
  // vào content của chính node Điều, để bấm vào node Điều xem được luôn nội dung gộp thay vì rỗng.
  for (const [number, entry] of flatNodes) {
    if (parentNumber(number) !== null || entry.data.content) continue; // không phải Điều, hoặc đã có content thật
    const childEntries = Array.from(flatNodes.values())
      .filter((e) => e.id !== number && e.id.startsWith(`${number}.`))
      .sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
    if (!childEntries.length) continue;
    const combinedContent = childEntries
      .map((e) => `**${e.data.is_appendix ? "Appendix" : "Clause"} ${e.data.number}**${e.data.title ? ` - ${e.data.title}` : ""}\n\n${e.data.content || "(content not retrieved)"}`)
      .join("\n\n---\n\n");
    entry.data = {
      ...entry.data,
      title: entry.data.title || `Combined ${childEntries.length} sub-clauses`,
      content: combinedContent,
    };
  }

  const nodes: Node[] = [
    {
      id: AGREEMENT_ID,
      type: "evidence",
      position: { x: 0, y: 0 },
      data: {
        kind: "agreement", number: "", title: contractName || "Contract", isAppendix: false, matched: false,
        score: null, selected: false, isStub: false,
      } as unknown as Record<string, unknown>,
    },
  ];
  for (const [number, { data }] of flatNodes) {
    const isArticleTier = parentNumber(number) === null;
    const isStub = !data.content && !data.matched;
    nodes.push({
      id: number,
      type: "evidence",
      position: { x: 0, y: 0 },
      data: {
        kind: isArticleTier ? "article" : "clause", number: data.number, title: data.title, isAppendix: data.is_appendix,
        matched: data.matched, score: data.score, selected: false, isStub,
      } as unknown as Record<string, unknown>,
    });
  }

  const edges: Edge[] = containsEdges.map(({ source, target }) => ({
    id: `contains:${source}->${target}`,
    source,
    target,
    label: RELATION_LABEL.CONTAINS,
    data: { relation: "CONTAINS" },
    style: { stroke: RELATION_COLOR.CONTAINS, strokeWidth: 1.5 },
    labelStyle: { fill: "#94a3b8", fontSize: 9, fontWeight: 500 },
    labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9 },
  }));
  for (const { source, target, relation } of crossEdges.values()) {
    if (source === target) continue;
    edges.push({
      id: `rel:${source}->${target}:${relation}`,
      source,
      target,
      label: RELATION_LABEL[relation] || relation,
      data: { relation },
      style: { stroke: RELATION_COLOR[relation] || "#94a3b8", strokeDasharray: DASHED_RELATIONS.has(relation) ? "5 4" : undefined },
      labelStyle: { fill: RELATION_COLOR[relation] || "#64748b", fontSize: 10, fontWeight: 600 },
      labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9 },
    });
  }

  return { nodes, edges, flatNodes };
}

function NodeDetail({ node, contractName }: { node: EvidenceNode | "agreement"; contractName: string }) {
  if (node === "agreement") {
    return (
      <div className="rounded-xl border border-border bg-white shadow-sm p-3">
        <span className="text-sm font-bold text-accent-dark">{contractName || "Contract"}</span>
        <p className="mt-1.5 text-[0.74rem] text-muted">Root node of the whole diagram - every Article, Clause, and Appendix belongs to this contract.</p>
      </div>
    );
  }

  const html = marked.parse(node.content || "", { async: false }) as string;
  return (
    <div className="rounded-xl border border-border bg-white shadow-sm p-3">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-bold">{node.is_appendix ? `Appendix ${node.number}` : `Clause ${node.number}`}</span>
        {node.matched && <span className="text-[0.62rem] font-semibold px-1.5 py-0.5 rounded-full text-accent-dark bg-accent-tint">Direct match</span>}
      </div>
      {node.title && <p className="text-[0.76rem] text-muted mb-1.5">{node.title}</p>}
      {node.score !== null && (
        <div className="mb-1.5 text-[0.72rem] text-muted">
          Relevance: <span className="font-mono text-text">{node.score.toFixed(4)}</span>
        </div>
      )}
      {node.relation && (
        <div className="mb-1.5 text-[0.72rem] text-muted">
          Relation: <span className="text-text font-medium">{RELATION_LABEL[node.relation] || node.relation}</span>
        </div>
      )}
      <div className="border-t border-border pt-2 mt-1.5 max-h-64 overflow-y-auto">
        {node.content ? (
          <div className="markdown-body text-[0.76rem] leading-relaxed text-text [&_p]:my-1.5" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <p className="text-[0.76rem] text-muted italic">This node only represents the hierarchy - no detailed content has been retrieved.</p>
        )}
      </div>
    </div>
  );
}

export default function GraphView({ evidences, contractName }: { evidences: Evidence[] | null; contractName: string }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(new Set(KIND_OPTIONS.map((o) => o.key)));
  const [enabledRelations, setEnabledRelations] = useState<Set<string>>(new Set(ALL_RELATIONS));

  // "layoutNodes"/"layoutEdges" = vị trí CHUẨN do Dagre tính - chỉ tính lại khi evidences/hợp đồng
  // đổi. "nodes" là state React Flow thật (draggable) - đồng bộ lại từ layoutNodes mỗi khi layout đổi.
  const { layoutNodes, layoutEdges, flatNodes } = useMemo(() => {
    if (!evidences || evidences.length === 0)
      return { layoutNodes: [] as Node[], layoutEdges: [] as Edge[], flatNodes: new Map<string, FlatNode>() };
    const built = buildUnifiedGraph(evidences, contractName);
    const laidOut = layoutGraph(built.nodes, built.edges);
    return { layoutNodes: laidOut.nodes, layoutEdges: laidOut.edges, flatNodes: built.flatNodes };
  }, [evidences, contractName]);

  const [nodes, setNodes] = useState<Node[]>(layoutNodes);
  useEffect(() => {
    setNodes(layoutNodes);
    setSelectedId(null);
  }, [layoutNodes]);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)), []);

  // Thả tay kéo: nếu vị trí mới KHÔNG đè lên node nào khác thì GIỮ NGUYÊN. Nếu đè, chỉ đẩy tới VỊ
  // TRÍ HỢP LỆ GẦN NHẤT (dịch chuyển tối thiểu để thoát chồng lấn, xem dragCollision.ts).
  const onNodeDragStop = useCallback((_: unknown, draggedNode: Node) => {
    setNodes((nds) => {
      if (!draggedNodeOverlapsAny(draggedNode, nds, NODE_WIDTH, NODE_HEIGHT)) return nds;
      const validPos = findNearestValidPosition(draggedNode, nds, NODE_WIDTH, NODE_HEIGHT);
      return nds.map((n) => (n.id === draggedNode.id ? { ...n, position: validPos } : n));
    });
  }, []);

  // Bỏ tích 1 LOẠI NỐT chỉ ẩn đúng các nốt của loại đó CÙNG các nốt con của riêng chúng (đi theo
  // cạnh CONTAINS - quan hệ phân cấp thật) - KHÔNG đụng tới phần còn lại của graph.
  //
  // Bỏ tích 1 QUAN HỆ chỉ CẮT cạnh quan hệ đó XUẤT PHÁT TỪ nốt đang chọn (vd chọn "Article 2" rồi
  // bỏ tích "Contains" thì chỉ cắt cạnh Article 2 -> Clause 2.1/2.2). Cắt 1 cạnh KHÔNG có nghĩa là
  // ẩn thẳng nốt đầu kia - nốt đó chỉ thực sự ẩn nếu sau khi cắt, nó KHÔNG còn đường nào khác nối
  // về Hợp đồng gốc nữa (vd Clause 1.1 vẫn còn "Contains" từ Article 1 dù bị "References" từ Article
  // 3 cắt, nên vẫn phải hiện). Chưa chọn nốt nào thì bỏ tích quan hệ chỉ ẩn CẠNH đó (xem visibleEdges
  // bên dưới), không ẩn nốt nào.
  const visibleNodeIds = useMemo(() => {
    const childrenOf = new Map<string, string[]>();
    for (const e of layoutEdges) {
      const relation = (e.data as { relation: string } | undefined)?.relation || "";
      const cut = selectedId != null && e.source === selectedId && !enabledRelations.has(relation);
      if (cut) continue;
      if (!childrenOf.has(e.source)) childrenOf.set(e.source, []);
      childrenOf.get(e.source)!.push(e.target);
    }
    const typeHidden = new Set<string>();
    for (const n of nodes) {
      if (!enabledTypes.has(kindKey(n.data as unknown as EvidenceFlowNodeData))) typeHidden.add(n.id);
    }
    // Truy hồi từ Hợp đồng gốc bằng các cạnh CÒN LẠI (đã trừ cạnh bị cắt ở trên, và bỏ qua nốt bị
    // ẩn do loại) - nốt nào không tới được coi là mất kết nối, phải ẩn.
    const reachable = new Set<string>();
    const queue = typeHidden.has(AGREEMENT_ID) ? [] : [AGREEMENT_ID];
    if (queue.length) reachable.add(AGREEMENT_ID);
    while (queue.length) {
      const cur = queue.shift()!;
      for (const next of childrenOf.get(cur) || []) {
        if (typeHidden.has(next) || reachable.has(next)) continue;
        reachable.add(next);
        queue.push(next);
      }
    }
    return reachable;
  }, [nodes, layoutEdges, enabledTypes, enabledRelations, selectedId]);
  const visibleNodes = useMemo(
    () =>
      nodes
        .map((n) => ({ ...n, data: { ...n.data, selected: n.id === selectedId } }))
        .filter((n) => visibleNodeIds.has(n.id)),
    [nodes, visibleNodeIds, selectedId],
  );
  // Chưa chọn nốt nào: bỏ tích 1 quan hệ ẩn TOÀN BỘ cạnh của quan hệ đó (không biết ẩn theo phạm vi
  // nào). Đã chọn 1 nốt: chỉ ẩn đúng cạnh quan hệ đó XUẤT PHÁT TỪ nốt đang chọn - cạnh cùng loại
  // quan hệ ở chỗ khác trên graph không bị ảnh hưởng.
  const visibleEdges = useMemo(
    () =>
      layoutEdges.filter((e) => {
        const relation = (e.data as { relation: string } | undefined)?.relation || "";
        if (!visibleNodeIds.has(e.source) || !visibleNodeIds.has(e.target)) return false;
        if (enabledRelations.has(relation)) return true;
        if (selectedId) return e.source !== selectedId;
        return false;
      }),
    [layoutEdges, enabledRelations, visibleNodeIds, selectedId],
  );

  const stats = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of nodes) counts.set(kindKey(n.data as unknown as EvidenceFlowNodeData), (counts.get(kindKey(n.data as unknown as EvidenceFlowNodeData)) || 0) + 1);
    return KIND_OPTIONS.filter((o) => counts.has(o.key)).map<StatRow>((o) => ({ key: o.key, label: o.label, dotClass: o.dotClass, count: counts.get(o.key)! }));
  }, [nodes]);

  const selectedNode: EvidenceNode | "agreement" | null =
    selectedId === AGREEMENT_ID ? "agreement" : selectedId ? flatNodes.get(selectedId)?.data ?? null : null;

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
    <GraphShell
      emptyMessage="No graph data for this answer yet."
      nodes={visibleNodes}
      edges={visibleEdges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={setSelectedId}
      onPaneClick={() => setSelectedId(null)}
      detailHint="Select a node on the diagram to see its details."
      detailContent={selectedNode && <NodeDetail node={selectedNode} contractName={contractName} />}
      nodeTypeOptions={KIND_OPTIONS}
      enabledTypes={enabledTypes}
      onToggleType={toggleType}
      relationOptions={RELATION_OPTIONS}
      enabledRelations={enabledRelations}
      onToggleRelation={toggleRelation}
      stats={stats}
      totalNodes={nodes.length}
      totalEdges={layoutEdges.length}
      minimapNodeColor={(n) => {
        const d = n.data as unknown as EvidenceFlowNodeData;
        if (d.kind === "agreement") return ACCENT;
        if (d.kind === "article") return "#6366f1";
        return d.isAppendix ? "#d97706" : d.matched ? ACCENT : "#94a3b8";
      }}
    />
  );
}
