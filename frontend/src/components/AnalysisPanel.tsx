import { useEffect, useState } from "react";
import { marked } from "marked";
import EvidencePanel from "./EvidencePanel";
import GraphView from "./GraphView";
import { badgeForEntry } from "./ChecklistPanel";
import { getSimilarClauses } from "../api";
import type { ReviewEntry } from "../review";
import type { EvidenceClause, SimilarClause, VerificationUnit } from "../types";

function durationLabel(seconds?: number): string {
  if (seconds === undefined || seconds === null) return "";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}p${s.toString().padStart(2, "0")}s`;
}

// Compact number: 11274 -> "11.3K", 944 -> "944" - dùng cho dòng usage cho gọn.
function compactNumber(n: number): string {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(1)}K`;
}

// "Căn cứ" - mỗi Điều/Khoản LLM chọn làm căn cứ (đã tra ngược từ số hiệu, xem checklist/evaluator.py
// ::resolve_evidence_clauses), render markdown NGUYÊN VĂN đầy đủ - nhưng THU GỌN mặc định (chỉ hiện
// vài dòng đầu) để danh sách nhiều Điều không chiếm hết màn hình, bấm để xem toàn bộ.
function EvidenceClauseRow({ c }: { c: EvidenceClause }) {
  const [expanded, setExpanded] = useState(false);
  // Thu gọn: text THUẦN 1 dòng (không markdown) - dùng "truncate" cắt chắc chắn đúng 1 dòng, tránh
  // line-clamp bị lệch do nội dung markdown có nhiều thẻ <p> (mỗi đoạn xuống dòng riêng). Mở rộng
  // mới render markdown đầy đủ.
  const preview = (c.text || "").replace(/\s+/g, " ").trim();
  const html = marked.parse(c.text || "", { async: false }) as string;
  return (
    <div
      className={`rounded-lg border bg-white overflow-hidden transition-colors ${
        expanded ? "border-accent/30" : "border-border hover:border-accent/30"
      }`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 text-left px-3 py-2"
      >
        <span className="shrink-0 text-[0.68rem] font-bold text-accent-dark bg-accent-tint rounded-md px-1.5 py-0.5">
          {c.number}
        </span>
        {/* Nhãn Điều/Phụ lục cha - chỉ hiện khi Khoản này KHÁC với Điều/Phụ lục gốc (vd "11.2" thuộc
            "Điều 11", hay "PL03.1" thuộc "Phụ lục 03") để biết ngay căn cứ nằm ở đâu mà không phải tự
            suy luận từ số hiệu - bỏ qua khi number == article_number (badge số hiệu đã đủ rõ). */}
        {c.number !== c.article_number && (
          <span className="shrink-0 text-[0.68rem] font-medium text-muted bg-black/5 rounded-md px-1.5 py-0.5">
            {c.is_appendix ? `Phụ lục ${c.article_number.slice(2)}` : `Điều ${c.article_number}`}
          </span>
        )}
        <span className="flex-1 min-w-0 truncate text-[0.8rem]">
          {c.title && <span className="font-medium">{c.title}</span>}
          {c.title && !expanded && preview && <span className="text-muted"> — </span>}
          {!expanded && <span className="text-muted">{preview}</span>}
        </span>
        <span className={`shrink-0 text-muted transition-transform ${expanded ? "-rotate-90" : "rotate-90"}`}>&#8250;</span>
      </button>
      {expanded && (
        <div className="markdown-body text-sm leading-relaxed px-3 pb-3 border-t border-border pt-2.5" dangerouslySetInnerHTML={{ __html: html }} />
      )}
    </div>
  );
}

// "Tài liệu tham chiếu" - với MỖI Điều khoản đã dùng làm căn cứ (evidence_clauses), tìm kiếm vector
// các Điều khoản NỘI DUNG TƯƠNG TỰ ở CÁC HỢP ĐỒNG KHÁC (không gọi LLM, chỉ vector search - xem
// GET /api/similar-clauses) để reviewer tham khảo cách viết lại. Tự tìm ngay khi mở tab, không cần
// bấm thêm nút - kết quả cache theo số hiệu Điều trong state, không tìm lại khi chuyển tab qua lại.
function ReferenceClauses({ contractId, clauses }: { contractId: number; clauses: EvidenceClause[] }) {
  const [results, setResults] = useState<Record<string, SimilarClause[] | "loading" | "error">>({});

  useEffect(() => {
    setResults({});
    for (const c of clauses) {
      setResults((prev) => ({ ...prev, [c.number]: "loading" }));
      getSimilarClauses(contractId, c.number)
        .then((r) => setResults((prev) => ({ ...prev, [c.number]: r })))
        .catch(() => setResults((prev) => ({ ...prev, [c.number]: "error" })));
    }
  }, [contractId, clauses]);

  if (clauses.length === 0) {
    return <p className="text-sm text-muted">No evidence clauses to look up references for.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {clauses.map((c) => {
        const r = results[c.number];
        return (
          <div key={c.number}>
            <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-1.5">
              Similar to Article {c.number}
              {c.title ? ` - ${c.title}` : ""}
            </div>
            {r === undefined || r === "loading" ? (
              <div className="text-sm text-muted flex items-center gap-1.5">
                <span className="spinner" /> Searching other contracts...
              </div>
            ) : r === "error" ? (
              <p className="text-sm text-fail">Failed to search for similar clauses.</p>
            ) : r.length === 0 ? (
              <p className="text-sm text-muted">No similar clauses found in other contracts.</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {r.map((s, i) => (
                  <div key={i} className="rounded-lg border border-border bg-white px-3 py-2">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="shrink-0 text-[0.68rem] font-bold text-accent-dark bg-accent-tint rounded-md px-1.5 py-0.5">{s.number}</span>
                      <span className="flex-1 min-w-0 truncate text-[0.78rem] font-medium">{s.contract_name}</span>
                      <span className="shrink-0 text-[0.7rem] font-mono text-muted">{s.score.toFixed(2)}</span>
                    </div>
                    <p className="text-[0.8rem] text-muted leading-relaxed m-0">{s.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function VerificationUnitRow({ u }: { u: VerificationUnit }) {
  const icon = u.result === "met" ? { mark: "✓", cls: "text-ok" } : u.result === "not_met" ? { mark: "✗", cls: "text-fail" } : { mark: "•", cls: "text-neutral" };
  return (
    <div className="flex items-start gap-1.5 text-[0.78rem] leading-snug">
      <span className={`font-bold shrink-0 ${icon.cls}`}>{icon.mark}</span>
      <span>{u.requirement}</span>
    </div>
  );
}

type Tab = "result" | "clauses" | "references" | "graph";

interface AnalysisPanelProps {
  entry: ReviewEntry | null;
  contractId: number | null;
  contractName: string;
  onAnalyzeItem: (itemId: string) => void;
}

export default function AnalysisPanel({ entry, contractId, contractName, onAnalyzeItem }: AnalysisPanelProps) {
  const [tab, setTab] = useState<Tab>("result");

  // Đổi mục checklist đang xem thì quay về tab "Kết quả phân tích" mặc định - không giữ tab "Graph
  // Flow" từ mục trước sang mục mới (dễ gây hiểu nhầm graph đang hiện là của mục nào).
  useEffect(() => {
    setTab("result");
  }, [entry?.item.id]);

  if (!entry) {
    return (
      <div className="flex-1 min-w-0 flex items-center justify-center border border-border rounded-2xl bg-white text-muted text-sm">
        Select a checklist item on the left to view the analysis results.
      </div>
    );
  }

  const { item, answer, status, errorMessage } = entry;
  const badge = badgeForEntry(entry);
  const nMet = answer?.verification_units.filter((u) => u.result === "met").length || 0;
  const nNotMet = answer?.verification_units.filter((u) => u.result === "not_met").length || 0;
  const nNote = answer?.verification_units.filter((u) => u.result === "not_applicable").length || 0;

  return (
    <div className="flex-1 min-w-0 flex flex-col border border-border rounded-2xl bg-white overflow-hidden">
      <div className="px-4 pt-3.5 flex items-center gap-2 shrink-0">
        <h3 className="text-[0.92rem] font-bold m-0 truncate flex-1">{item.question}</h3>
        <span className={`shrink-0 text-[0.68rem] font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}>{badge.label}</span>
        {status !== "running" && (
          <button
            type="button"
            onClick={() => onAnalyzeItem(item.id)}
            title={status === "pending" ? "Analyze this item" : "Re-analyze this item"}
            className="shrink-0 flex items-center gap-1 text-[0.72rem] font-semibold border border-border rounded-full pl-2 pr-2.5 py-1 text-muted hover:border-accent hover:text-accent hover:bg-accent-tint transition-colors"
          >
            <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
            {status === "pending" ? "Analyze" : "Re-analyze"}
          </button>
        )}
      </div>

      <div className="px-4 flex gap-4 border-b border-border shrink-0 mt-2">
        {(["result", "clauses", "references", "graph"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`py-2 text-[0.8rem] font-semibold border-b-2 -mb-px whitespace-nowrap ${
              tab === t ? "border-accent text-accent-dark" : "border-transparent text-muted hover:text-text"
            }`}
          >
            {t === "result" ? "Result" : t === "clauses" ? "Related Clauses" : t === "references" ? "References" : "Graph"}
          </button>
        ))}
      </div>

      {status === "pending" || status === "running" ? (
        <div className="flex-1 flex flex-col items-center justify-center text-muted text-sm gap-2">
          {status === "running" && <span className="spinner" />}
          {status === "running" ? "Analyzing..." : "This item hasn't been checked yet."}
        </div>
      ) : status === "error" ? (
        <div className="flex-1 flex items-center justify-center text-fail text-sm p-4 text-center">{errorMessage}</div>
      ) : !answer ? null : tab === "graph" ? (
        <div className="flex-1 min-h-0 flex flex-col">
          <GraphView evidences={answer.evidences} contractName={contractName} />
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          {tab === "result" && (
            <>
              <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-1">Conclusion</div>
              <p className="text-sm mb-3">{answer.reasoning}</p>

              <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-1.5">Evidence</div>
              {(answer.evidence_clauses || []).length > 0 ? (
                <div className="mb-3 flex flex-col gap-1.5">
                  {(answer.evidence_clauses || []).map((c, i) => (
                    <EvidenceClauseRow key={i} c={c} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted mb-3">No clauses were cited as evidence.</p>
              )}

              <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-1">Recommendation</div>
              {(answer.recommendation || []).length > 0 ? (
                <div className="text-sm mb-3 flex flex-col gap-1.5">
                  {answer.recommendation.map((line, i) => (
                    <p key={i} className="m-0">
                      {line}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="text-sm mb-3">(no recommendation - already passed)</p>
              )}

              {answer.verification_units.length > 0 && (
                <div className="mt-4 border-t border-border pt-3">
                  <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-2">Quick Assessment</div>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <div className="text-[0.7rem] font-semibold text-ok mb-1">Pass Criteria ({nMet})</div>
                      {answer.verification_units.filter((u) => u.result === "met").map((u, i) => <VerificationUnitRow key={i} u={u} />)}
                    </div>
                    <div>
                      <div className="text-[0.7rem] font-semibold text-fail mb-1">Fail Criteria ({nNotMet})</div>
                      {answer.verification_units.filter((u) => u.result === "not_met").map((u, i) => <VerificationUnitRow key={i} u={u} />)}
                    </div>
                    <div>
                      <div className="text-[0.7rem] font-semibold text-neutral mb-1">Note ({nNote})</div>
                      {answer.verification_units.filter((u) => u.result === "not_applicable").map((u, i) => <VerificationUnitRow key={i} u={u} />)}
                    </div>
                  </div>
                </div>
              )}

              <div className="mt-4 border-t border-border pt-3 text-[0.76rem] text-muted flex flex-wrap items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
                Confidence {answer.confidence}%
                {answer.usage && (
                  <>
                    {" · "}
                    {compactNumber(answer.usage.input_tokens || 0)} input
                    {" · "}
                    {compactNumber(answer.usage.cached_input_tokens || 0)} cached
                    {" · "}
                    {compactNumber(answer.usage.output_tokens || 0)} output
                    {answer.usage.cost_usd != null && ` · $${answer.usage.cost_usd.toFixed(4)}`}
                    {answer.usage.duration_seconds != null && ` · ${durationLabel(answer.usage.duration_seconds)}`}
                  </>
                )}
              </div>
            </>
          )}
          {tab === "clauses" && <EvidencePanel groups={answer.clauses} inline />}
          {tab === "references" && contractId != null && (
            <ReferenceClauses contractId={contractId} clauses={answer.evidence_clauses || []} />
          )}
        </div>
      )}
    </div>
  );
}
