import { Handle, Position, type NodeProps } from "@xyflow/react";

export type EvidenceNodeKind = "agreement" | "article" | "clause";

export interface EvidenceFlowNodeData {
  kind: EvidenceNodeKind;
  number: string;
  title: string;
  isAppendix: boolean;
  matched: boolean;
  score: number | null;
  selected: boolean;
  isStub: boolean; // node cha suy ra từ số hiệu (vd "Điều 11" chỉ để nối cây), không có content thật
  [key: string]: unknown;
}

// Node tuỳ biến cho 3 tầng của graph: agreement (gốc Hợp đồng) > article (Điều/Phụ lục cha, có thể
// là "stub" suy ra từ số hiệu nếu không nằm trong evidences) > clause (Khoản/Phụ lục con - matched
// khớp trực tiếp câu hỏi, khác context chỉ kéo theo qua quan hệ đồ thị). Nền trắng, màu đỏ
// (--color-accent) dành riêng cho node quan trọng nhất (Hợp đồng gốc + Khoản khớp trực tiếp).
export default function EvidenceFlowNode({ data }: NodeProps & { data: EvidenceFlowNodeData }) {
  const { kind, number, title, isAppendix, matched, score, selected, isStub } = data;

  if (kind === "agreement") {
    return (
      <div
        className={`w-[220px] rounded-xl border-2 border-accent bg-accent-tint px-3 py-2.5 shadow-md ${selected ? "ring-2 ring-accent/50" : ""}`}
      >
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-accent" />
          <span className="text-[0.68rem] font-bold text-accent-dark truncate">Contract</span>
        </div>
        <p className="mt-1 text-[0.76rem] leading-snug text-text font-semibold line-clamp-2">{title}</p>
        <Handle type="source" position={Position.Bottom} className="!bg-accent !w-1.5 !h-1.5 !border-0" />
      </div>
    );
  }

  const palette =
    kind === "article"
      ? { border: "border-indigo-400", ring: "ring-indigo-300", dot: "bg-indigo-500", badge: "text-indigo-700 bg-indigo-50" }
      : isAppendix
        ? { border: "border-amber-400", ring: "ring-amber-300", dot: "bg-amber-500", badge: "text-amber-700 bg-amber-50" }
        : matched
          ? { border: "border-accent", ring: "ring-accent/40", dot: "bg-accent", badge: "text-accent-dark bg-accent-tint" }
          : { border: "border-border", ring: "ring-slate-300", dot: "bg-slate-400", badge: "text-muted bg-black/5" };

  const label = kind === "article" ? `Article ${number}` : isAppendix ? `Appendix ${number}` : `Clause ${number}`;

  return (
    <div
      className={`w-[220px] rounded-xl border bg-white px-3 py-2.5 shadow-sm transition-shadow ${palette.border} ${
        selected ? `ring-2 ${palette.ring}` : ""
      } ${isStub ? "opacity-70" : ""}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-400 !w-1.5 !h-1.5 !border-0" />
      <div className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${palette.dot}`} />
        <span className="text-[0.68rem] font-bold text-text truncate">{label}</span>
        {matched && <span className={`ml-auto text-[0.62rem] font-semibold px-1.5 py-0.5 rounded-full shrink-0 ${palette.badge}`}>Direct match</span>}
      </div>
      <p className="mt-1 text-[0.72rem] leading-snug text-muted line-clamp-2">
        {isStub ? "Content not retrieved - shown only to represent the hierarchy" : title || "No dedicated title"}
      </p>
      {score !== null && (
        <div className="mt-1.5 flex items-center gap-1">
          <div className="h-1 flex-1 rounded-full bg-black/8 overflow-hidden">
            <div className={`h-full rounded-full ${palette.dot}`} style={{ width: `${Math.round(score * 100)}%` }} />
          </div>
          <span className="text-[0.62rem] font-mono text-muted">{score.toFixed(2)}</span>
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-slate-400 !w-1.5 !h-1.5 !border-0" />
    </div>
  );
}
