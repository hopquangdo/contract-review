import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { FullGraphNodeType } from "../../types";

export interface FullGraphNodeData {
  id: string;
  type: FullGraphNodeType;
  label: string;
  number?: string;
  role?: string;
  depth: number;
  selected?: boolean;
  highlighted?: boolean; // được trích dẫn ở mục checklist đang xem (xem FullGraphView::highlightNumbers)
  [key: string]: unknown;
}

// Bảng màu theo loại node THẬT trong Neo4j (Contract/Section/Clause/Appendix/Party/GoverningLaw/
// DisputeResolution) - dùng chung giữa node card, MiniMap và legend (xem FullGraphView.tsx) để
// không lệch màu giữa các nơi hiển thị.
export const NODE_TYPE_STYLE: Record<FullGraphNodeType, { dot: string; border: string; text: string; bg: string; label: string }> = {
  Contract: { dot: "bg-accent", border: "border-accent", text: "text-accent-dark", bg: "bg-accent-tint", label: "Contract" },
  Section: { dot: "bg-sky-500", border: "border-sky-400", text: "text-sky-700", bg: "bg-sky-50", label: "Section" },
  Clause: { dot: "bg-emerald-500", border: "border-emerald-400", text: "text-emerald-700", bg: "bg-emerald-50", label: "Article/Clause" },
  Appendix: { dot: "bg-amber-500", border: "border-amber-400", text: "text-amber-700", bg: "bg-amber-50", label: "Appendix" },
  Party: { dot: "bg-teal-500", border: "border-teal-400", text: "text-teal-700", bg: "bg-teal-50", label: "Party" },
  GoverningLaw: { dot: "bg-violet-500", border: "border-violet-400", text: "text-violet-700", bg: "bg-violet-50", label: "Governing law" },
  DisputeResolution: { dot: "bg-rose-500", border: "border-rose-400", text: "text-rose-700", bg: "bg-rose-50", label: "Dispute resolution" },
};

export default function FullGraphNode({ data }: NodeProps & { data: FullGraphNodeData }) {
  const { type, label, number, depth, selected, highlighted } = data;
  const style = NODE_TYPE_STYLE[type];
  const isCenter = depth === 0;

  return (
    <div
      className={`rounded-full border bg-white shadow-sm px-3 py-1.5 flex items-center gap-1.5 ${style.border} ${
        isCenter ? "w-[180px] justify-center py-2.5 shadow-md border-2" : "w-[150px]"
      } ${selected ? "ring-2 ring-accent/50" : highlighted ? "ring-2 ring-accent/70 shadow-md" : ""}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-400 !w-1 !h-1 !border-0 !opacity-0" />
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
      <div className="min-w-0">
        <div className={`text-[0.66rem] font-bold truncate ${isCenter ? style.text : "text-text"}`}>
          {number ? `${style.label} ${number}` : label}
        </div>
        {number && label && <div className="text-[0.6rem] text-muted truncate">{label}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-slate-400 !w-1 !h-1 !border-0 !opacity-0" />
    </div>
  );
}
