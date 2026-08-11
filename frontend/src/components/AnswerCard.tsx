import type { UsageInfo } from "../types";

const USD_TO_VND = 26000; // tỷ giá ước tính, không lấy realtime - chỉ để tham khảo tương đối

function statusCardClass(label: string): string {
  if (["Đạt", "Có thông tin"].includes(label)) return "bg-ok-bg text-ok";
  if (["Chưa đạt", "Vi phạm", "Không đạt"].includes(label)) return "bg-fail-bg text-fail";
  if (["Không có thông tin", "Có một phần thông tin"].includes(label)) return "bg-warn-bg text-warn";
  return "bg-neutral-bg text-neutral";
}

function durationLabel(seconds?: number): string {
  if (seconds === undefined || seconds === null) return "";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}p${s.toString().padStart(2, "0")}s`;
}

function usageLabel(usage?: UsageInfo | null): string {
  if (!usage) return "";
  const tokens = (usage.input_tokens || 0) + (usage.output_tokens || 0);
  let costStr = "";
  if (usage.cost_usd !== null && usage.cost_usd !== undefined) {
    const vnd = usage.cost_usd * USD_TO_VND;
    const vndStr = vnd < 1 ? "<1" : Math.round(vnd).toLocaleString("vi-VN");
    costStr = ` · $${usage.cost_usd.toFixed(4)} (~${vndStr}đ)`;
  }
  const durationStr = usage.duration_seconds !== undefined ? ` · ${durationLabel(usage.duration_seconds)}` : "";
  return ` · ${tokens} token${costStr}${durationStr}`;
}

interface AnswerCardProps {
  status: string;
  evidence: string;
  reasoning: string;
  recommendation: string;
  confidence: number;
  usage?: UsageInfo | null;
  onShowEvidence: () => void;
  evidenceActive: boolean;
}

export default function AnswerCard({ status, evidence, reasoning, recommendation, confidence, usage, onShowEvidence, evidenceActive }: AnswerCardProps) {
  return (
    <div className="rounded-2xl border border-border bg-white overflow-hidden w-full">
      <div className="px-[1.1rem] pt-[0.95rem] pb-2">
        <div className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 mb-3 font-bold text-[0.82rem] ${statusCardClass(status)}`}>
          <span className="w-1.5 h-1.5 rounded-full bg-current shrink-0" />
          {status}
        </div>

        <div className="text-[0.78rem] font-bold uppercase tracking-wide text-muted mt-0 mb-1">Căn cứ</div>
        <div className="bg-black/2 border border-border rounded-[10px] px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">{evidence}</div>

        <div className="text-[0.78rem] font-bold uppercase tracking-wide text-muted mt-2.5 mb-1">Lý do</div>
        <p className="my-1.5 text-sm leading-relaxed">{reasoning}</p>

        <div className="text-[0.78rem] font-bold uppercase tracking-wide text-muted mt-2.5 mb-1">Đề xuất</div>
        <p className="my-1.5 text-sm leading-relaxed">{recommendation}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 px-[1.1rem] py-2.5 border-t border-border bg-black/[0.015] text-[0.8rem] text-muted">
        <span className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
        Độ tin cậy: {confidence}/100{usageLabel(usage)}
        <span
          onClick={onShowEvidence}
          className={`ml-auto text-[0.8rem] font-semibold cursor-pointer underline underline-offset-2 ${
            evidenceActive ? "text-accent" : "text-accent-dark hover:text-accent"
          }`}
        >
          Xem trích dẫn
        </span>
      </div>
    </div>
  );
}
