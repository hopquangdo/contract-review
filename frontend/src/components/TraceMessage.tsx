import { useState } from "react";
import AnswerCard from "./AnswerCard";
import type { SingleAnswer } from "../types";

export type TraceStep =
  | { step: "generate_queries"; queries: string[] }
  | { step: "retrieval"; n_clauses: number; articles: { article_number: string; article_title: string }[] };

const STEP_META: Record<TraceStep["step"], { title: string }> = {
  generate_queries: {  title: "Sinh truy vấn tìm kiếm" },
  retrieval: {  title: "Tìm kiếm trên hợp đồng" },
};

function StepDetails({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(true);
  const meta = STEP_META[step.step];
  const items = step.step === "generate_queries" ? step.queries : step.articles.map((a) => (a.article_title ? `Điều ${a.article_number}. ${a.article_title}` : `Điều ${a.article_number}`));
  const subtitle = step.step === "generate_queries" ? `${step.queries.length} truy vấn` : `${step.n_clauses} Điều`;

  return (
    <div className="border border-border rounded-[10px] overflow-hidden bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-1.5 px-2.5 py-2 text-[0.8rem] font-semibold text-left outline-none focus-visible:ring-2 focus-visible:ring-accent-tint"
      >
        <span>
          {meta.title} · {subtitle}
        </span>
        <span className={`ml-auto text-muted transition-transform ${open ? "-rotate-90" : "rotate-90"}`}>&#8250;</span>
      </button>
      {open && (
        <div className="px-3.5 pt-0.5 pb-2.5 pl-8 text-[0.8rem] text-muted">
          {items.length ? (
            <ul className="my-0.5 pl-4 list-disc">
              {items.map((it, i) => (
                <li key={i} className="my-0.5">
                  {it}
                </li>
              ))}
            </ul>
          ) : (
            <p>Không có kết quả.</p>
          )}
        </div>
      )}
    </div>
  );
}

interface TraceMessageProps {
  steps: TraceStep[];
  answer: SingleAnswer | null;
  error: string | null;
  done: boolean;
  onShowEvidence: () => void;
  evidenceActive: boolean;
}

export default function TraceMessage({ steps, answer, error, done, onShowEvidence, evidenceActive }: TraceMessageProps) {
  const [traceOpen, setTraceOpen] = useState(true);

  return (
    <div className="flex flex-col gap-2 w-full">
      <div className="rounded-2xl border border-border bg-white overflow-hidden">
        <button
          type="button"
          onClick={() => setTraceOpen((o) => !o)}
          className="w-full flex items-center gap-2 px-[1.1rem] py-2.5 text-[0.85rem] font-semibold text-muted hover:text-text outline-none focus-visible:ring-2 focus-visible:ring-accent-tint"
        >
          {!done && <span className="spinner" />}
          <span>{done ? `Đã hoàn thành ${steps.length} bước` : "Đang xử lý..."}</span>
          <span className={`ml-auto text-[0.85rem] transition-transform ${traceOpen ? "rotate-90" : ""}`}>&#8250;</span>
        </button>
        {traceOpen && (
          <div className="flex flex-col gap-1.5 px-[1.1rem] pb-3">
            {steps.map((s, i) => (
              <StepDetails key={i} step={s} />
            ))}
          </div>
        )}
      </div>

      {answer && (
        <AnswerCard
          status={answer.status}
          evidence={answer.evidence}
          reasoning={answer.reasoning}
          recommendation={answer.recommendation}
          confidence={answer.confidence}
          usage={answer.usage}
          onShowEvidence={onShowEvidence}
          evidenceActive={evidenceActive}
        />
      )}
      {error && (
        <div className="rounded-2xl border border-border bg-white p-4 text-sm">
          <p className="m-0">{error}</p>
        </div>
      )}
    </div>
  );
}
