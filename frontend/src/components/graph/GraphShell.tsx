import { ReactFlow, Background, Controls, MiniMap, useReactFlow, type Edge, type Node, type NodeTypes, type OnNodesChange, type OnNodeDrag } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useRef, type ReactNode } from "react";

// ReactFlow "fitView" (prop) chỉ tự fit đúng 1 LẦN lúc mount - nếu "nodes" đến SAU (vd
// FullGraphView đợi ELK.js tính layout xong mới setNodes), lúc mount "nodes" vẫn rỗng nên fitView
// coi như fit vào "không có gì", graph load xong sau đó không tự zoom-to-fit nữa (phải tự kéo/zoom
// tay). Component con này (đặt BÊN TRONG <ReactFlow>, dùng được useReactFlow() nhờ context nội bộ
// của ReactFlow) tự gọi lại fitView() đúng lúc "nodes" chuyển từ rỗng -> có dữ liệu.
function FitViewOnNodesReady({ nodeCount }: { nodeCount: number }) {
  const { fitView } = useReactFlow();
  const prevCount = useRef(0);
  useEffect(() => {
    if (nodeCount > 0 && prevCount.current === 0) {
      requestAnimationFrame(() => fitView({ padding: 0.2, duration: 200 }));
    }
    prevCount.current = nodeCount;
  }, [nodeCount, fitView]);
  return null;
}

export interface NodeTypeOption {
  key: string;
  label: string;
  dotClass: string; // Tailwind class for the color dot (e.g. "bg-emerald-500")
}

export interface RelationOption {
  key: string;
  label: string; // shown in the checkbox - matches the real Neo4j relationship name
  color: string; // hex color (used for the edge swatch in the checkbox)
}

export interface StatRow {
  key: string;
  label: string;
  dotClass: string;
  count: number;
}

// Shared shell for every graph view (GraphView - evidence tree for a single question, FullGraphView -
// the whole contract): left sidebar (node type/relation filters + stats) + ReactFlow canvas in the
// middle + right panel (selected node detail), all sharing the same Background/Controls/MiniMap chrome.
// This component only owns LAYOUT + CHROME - filtering nodes/edges by type/relation is still computed
// by each page (pass in ALREADY FILTERED "nodes"/"edges"), keeping the different business logic
// (evidences vs full graph) out of this shared component.
interface GraphShellProps {
  loading?: boolean;
  loadingLabel?: string;
  emptyMessage?: string;
  nodes: Node[];
  edges: Edge[];
  nodeTypes: NodeTypes;
  onNodesChange: OnNodesChange;
  onNodeDragStop: OnNodeDrag;
  onNodeClick: (id: string) => void;
  onPaneClick: () => void;
  detailContent: ReactNode;
  detailHint?: string;
  nodeTypeOptions: NodeTypeOption[];
  enabledTypes: Set<string>;
  onToggleType: (key: string) => void;
  relationOptions: RelationOption[];
  enabledRelations: Set<string>;
  onToggleRelation: (key: string) => void;
  stats: StatRow[];
  totalNodes: number;
  totalEdges: number;
  minimapNodeColor: (n: Node) => string;
}

export default function GraphShell({
  loading, loadingLabel, emptyMessage, nodes, edges, nodeTypes, onNodesChange, onNodeDragStop, onNodeClick, onPaneClick,
  detailContent, nodeTypeOptions, enabledTypes, onToggleType, relationOptions, enabledRelations, onToggleRelation,
  stats, totalNodes, totalEdges, minimapNodeColor,
}: GraphShellProps) {
  if (totalNodes === 0 && !loading) {
    return <div className="flex-1 flex items-center justify-center text-muted text-sm bg-white">{emptyMessage || "No graph data yet."}</div>;
  }

  return (
    <div className="flex-1 min-h-0 flex">
      <div className="w-64 shrink-0 overflow-y-auto p-3 text-sm">
        <div className="rounded-xl border border-border bg-white shadow-sm p-3 flex flex-col gap-3">
          {nodeTypeOptions.length > 0 && (
            <div>
              <h4 className="text-[0.7rem] font-bold uppercase tracking-wider text-muted mb-1.5">Node types</h4>
              <div className="flex flex-col gap-1">
                {nodeTypeOptions.map((t) => (
                  <label key={t.key} className="flex items-center gap-2 text-[0.8rem] cursor-pointer">
                    <input type="checkbox" checked={enabledTypes.has(t.key)} onChange={() => onToggleType(t.key)} className="accent-accent" />
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${t.dotClass}`} />
                    {t.label}
                  </label>
                ))}
              </div>
            </div>
          )}

          {relationOptions.length > 0 && (
            <div className={nodeTypeOptions.length > 0 ? "border-t border-border pt-3" : ""}>
              <h4 className="text-[0.7rem] font-bold uppercase tracking-wider text-muted mb-1.5">Relations</h4>
              <div className="flex flex-col gap-1">
                {relationOptions.map((r) => (
                  <label key={r.key} className="flex items-center gap-2 text-[0.78rem] cursor-pointer">
                    <input type="checkbox" checked={enabledRelations.has(r.key)} onChange={() => onToggleRelation(r.key)} className="accent-accent" />
                    <span className="w-3 h-0.5 shrink-0" style={{ backgroundColor: r.color }} />
                    {r.label}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className={nodeTypeOptions.length > 0 || relationOptions.length > 0 ? "border-t border-border pt-3" : ""}>
            <h4 className="text-[0.7rem] font-bold uppercase tracking-wider text-muted mb-1.5">Overview</h4>
            <div className="flex flex-col gap-1 text-[0.8rem]">
              {stats.map((s) => (
                <div key={s.key} className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-muted">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dotClass}`} />
                    {s.label}
                  </span>
                  <span className="font-semibold">{s.count}</span>
                </div>
              ))}
              <div className="flex items-center justify-between border-t border-border mt-1 pt-1">
                <span className="text-muted">Total nodes</span>
                <span className="font-semibold">{totalNodes}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Total relations</span>
                <span className="font-semibold">{totalEdges}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 min-w-0 relative m-3 rounded-xl border border-border overflow-hidden">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/70 text-muted text-sm gap-2">
            <span className="spinner" /> {loadingLabel || "Loading..."}
          </div>
        )}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={(_, n) => onNodeClick(n.id)}
          onPaneClick={onPaneClick}
          fitView
          minZoom={0.05}
          proOptions={{ hideAttribution: true }}
          colorMode="light"
        >
          <FitViewOnNodesReady nodeCount={nodes.length} />
          <Background color="#e5e7eb" gap={24} />
          <Controls className="!bg-white !border-border !shadow-sm [&_button]:!bg-white [&_button]:!border-border [&_button]:!fill-text" />
          <MiniMap
            pannable
            zoomable
            style={{ width: 120, height: 90 }}
            className="!bg-white !border !border-border !shadow-sm [&_.react-flow__minimap-mask]:!stroke-none"
            maskColor="rgba(255,255,255,0.7)"
            nodeColor={minimapNodeColor}
          />
        </ReactFlow>
      </div>

      {detailContent && (
        <div className="w-72 shrink-0 overflow-y-auto p-3 text-sm">
          <div className="rounded-xl border border-border bg-white shadow-sm p-3">
            <h4 className="text-[0.7rem] font-bold uppercase tracking-wider text-muted mb-1.5">Selected node</h4>
            {detailContent}
          </div>
        </div>
      )}
    </div>
  );
}
