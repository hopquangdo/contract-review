import { useState } from "react";
import type { ReviewEntry } from "../review";

export function badgeForEntry(entry: ReviewEntry): { label: string; cls: string } {
  if (entry.status === "pending") return { label: "Pending", cls: "bg-neutral-bg text-neutral" };
  if (entry.status === "running") return { label: "Checking...", cls: "bg-warn-bg text-warn" };
  if (entry.status === "error") return { label: "Error", cls: "bg-fail-bg text-fail" };
  const isPass = entry.answer?.status === "Đạt";
  return isPass ? { label: "Pass", cls: "bg-ok-bg text-ok" } : { label: "Fail", cls: "bg-fail-bg text-fail" };
}

const USD_TO_VND = 26000; // tỷ giá ước tính, không lấy realtime - chỉ để tham khảo tương đối

function durationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}p${s.toString().padStart(2, "0")}s`;
}

interface ChecklistPanelProps {
  checklistName: string;
  entries: ReviewEntry[];
  runStatus: "idle" | "running" | "done";
  selectedItemId: string | null;
  onSelectItem: (itemId: string) => void;
  onStartAnalysis: () => void;
}

// Panel 1 - CHỈ danh sách checklist (câu hỏi + trạng thái) - nội dung phân tích chi tiết của mục
// đang chọn hiển thị ở panel 2 (xem AnalysisPanel.tsx), không lặp lại ở đây.
export default function ChecklistPanel({
  checklistName, entries, runStatus, selectedItemId, onSelectItem, onStartAnalysis,
}: ChecklistPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const doneCount = entries.filter((e) => e.status === "done" || e.status === "error").length;
  const total = entries.length;
  const percent = total ? Math.round((doneCount / total) * 100) : 0;

  if (collapsed) {
    return (
      <div className="w-12 shrink-0 flex flex-col items-center border border-border rounded-2xl bg-white overflow-hidden py-3 gap-3">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title="Expand Checklist Analysis"
          className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-black/5 text-muted"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
        <div className="text-[0.7rem] text-muted font-semibold [writing-mode:vertical-rl] rotate-180 select-none">
          {doneCount}/{total} · {percent}%
        </div>
      </div>
    );
  }

  // Tổng chi phí CẢ checklist - cộng dồn usage thật của từng mục đã chấm xong (không ước lượng).
  const totalUsage = entries.reduce(
    (acc, e) => {
      if (!e.answer?.usage) return acc;
      acc.inputTokens += e.answer.usage.input_tokens || 0;
      acc.cachedInputTokens += e.answer.usage.cached_input_tokens || 0;
      acc.outputTokens += e.answer.usage.output_tokens || 0;
      if (e.answer.usage.cost_usd != null) acc.costUsd += e.answer.usage.cost_usd;
      acc.durationSeconds += e.answer.usage.duration_seconds || 0;
      return acc;
    },
    { inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, costUsd: 0, durationSeconds: 0 },
  );

  return (
    <div className="w-[26rem] shrink-0 flex flex-col border border-border rounded-2xl bg-white overflow-hidden">
      <div className="px-4 pt-3.5 pb-2.5 border-b border-border">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[0.9rem] font-bold m-0">Checklist Analysis</h3>
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            title="Collapse"
            className="w-6 h-6 -mr-1 flex items-center justify-center rounded-lg hover:bg-black/5 text-muted shrink-0"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
        </div>
        <div className="text-[0.78rem] font-semibold border border-border rounded-lg px-2.5 py-1.5 mb-2 truncate">{checklistName}</div>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded-full bg-black/8 overflow-hidden">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${percent}%` }} />
          </div>
          <span className="text-[0.72rem] text-muted shrink-0">
            {doneCount}/{total} items · {percent}%
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {entries.length === 0 && <div className="text-muted text-sm text-center py-6">No items found.</div>}
        {entries.map((entry) => {
          const badge = badgeForEntry(entry);
          const active = entry.item.id === selectedItemId;
          return (
            <div
              key={entry.item.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelectItem(entry.item.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") onSelectItem(entry.item.id);
              }}
              className={`w-full text-left px-3.5 py-2.5 border-l-2 flex items-center gap-2 border-b border-border/60 cursor-pointer ${
                active ? "bg-accent-tint border-accent" : "border-transparent hover:bg-black/3"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="text-[0.82rem] font-semibold leading-snug">{entry.item.question}</div>
                <div className="text-[0.7rem] text-muted truncate">{entry.item.category}</div>
              </div>
              <span className={`shrink-0 text-[0.66rem] font-semibold px-1.5 py-0.5 rounded-full ${badge.cls}`}>
                {entry.status === "running" ? <span className="spinner !w-2.5 !h-2.5 !mr-0" /> : badge.label}
              </span>
            </div>
          );
        })}
      </div>

      <div className="border-t border-border p-3">
        {runStatus === "idle" ? (
          <button
            type="button"
            onClick={onStartAnalysis}
            disabled={total === 0}
            className="w-full text-[0.82rem] font-semibold bg-accent text-white rounded-lg py-2 hover:bg-accent-dark disabled:opacity-40"
          >
            Analyze
          </button>
        ) : runStatus === "running" ? (
          <button type="button" disabled className="w-full text-[0.82rem] font-semibold border border-border rounded-lg py-2 opacity-70 flex items-center justify-center gap-1.5">
            <span className="spinner" /> Analyzing {doneCount}/{total}...
          </button>
        ) : (
          <div className="text-[0.78rem] text-muted">
            <div className="flex items-center justify-between font-semibold text-text mb-1">
              <span>Total Cost</span>
              <span>{totalUsage.costUsd > 0 ? `$${totalUsage.costUsd.toFixed(4)}` : "—"}</span>
            </div>
            <div className="flex items-center justify-between">
<span className="text-xs text-muted-foreground">
  {totalUsage.inputTokens.toLocaleString("vi-VN")} input
  {totalUsage.cachedInputTokens > 0 &&
    ` · ${totalUsage.cachedInputTokens.toLocaleString("vi-VN")} cached`}
  {" · "}
  {totalUsage.outputTokens.toLocaleString("vi-VN")} output
</span>
     <span>
                {totalUsage.costUsd > 0 && `~${Math.round(totalUsage.costUsd * USD_TO_VND).toLocaleString("vi-VN")}đ`}
                {totalUsage.durationSeconds > 0 && ` · ${durationLabel(totalUsage.durationSeconds)}`}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
