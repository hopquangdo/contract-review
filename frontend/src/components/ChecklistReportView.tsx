import { useState } from "react";
import type { ChecklistEvaluation, ChecklistReport } from "../types";

function ChecklistItemRow({ ev, onOpen }: { ev: ChecklistEvaluation; onOpen: () => void }) {
  const [open, setOpen] = useState(false);
  const label = ev.status === "pass" ? "ĐẠT" : "VI PHẠM";
  return (
    <div className="border border-border rounded-[10px] px-3 py-2 mb-1.5">
      <button
        type="button"
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next) onOpen();
        }}
        className="w-full text-left text-sm font-semibold cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-accent-tint"
      >
        [{label}] [{ev.category}] {ev.question}
      </button>
      {open && (
        <div className="mt-2">
          <div className="text-[0.78rem] font-bold uppercase tracking-wide text-muted mb-1">Căn cứ</div>
          <div className="bg-black/2 border border-border rounded-[10px] px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">{ev.evidence}</div>
          <div className="text-[0.78rem] font-bold uppercase tracking-wide text-muted mt-2.5 mb-1">Lý do</div>
          <p className="my-1.5 text-sm leading-relaxed">{ev.reason}</p>
          <div className="text-[0.78rem] font-bold uppercase tracking-wide text-muted mt-2.5 mb-1">Đề xuất</div>
          <p className="my-1.5 text-sm leading-relaxed">{ev.proposal}</p>
        </div>
      )}
    </div>
  );
}

export default function ChecklistReportView({ report, onShowEvidence }: { report: ChecklistReport; onShowEvidence: (clauses: ChecklistEvaluation["cited_clauses"]) => void }) {
  const nPass = report.evaluations.filter((e) => e.status === "pass").length;
  const nFail = report.evaluations.length - nPass;
  const sorted = [...report.evaluations].sort((a, b) => (a.status === "fail" ? 0 : 1) - (b.status === "fail" ? 0 : 1));

  return (
    <div className="rounded-2xl border border-border bg-white p-[0.95rem_1.1rem_0.5rem] w-full">
      <p className="text-sm">
        Đã chấm <b>{report.checklist_name}</b> ({report.evaluations.length} mục): {nPass} đạt, {nFail} vi phạm
      </p>
      {sorted.map((ev, i) => (
        <ChecklistItemRow key={i} ev={ev} onOpen={() => onShowEvidence(ev.cited_clauses)} />
      ))}
    </div>
  );
}
