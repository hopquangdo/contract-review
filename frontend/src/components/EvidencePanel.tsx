import { useState } from "react";
import { marked } from "marked";
import type { ClauseGroup, ClauseItem } from "../types";

function scoreLabel(score: number | null): string {
  return score === null || score === undefined ? "Opening article · background context" : `Relevance ${score}`;
}

// Hiển thị đúng cấu trúc graph thật: 1 Clause -[:HAS_EXCERPT]-> nhiều Excerpt, mỗi Excerpt là 1
// khối riêng biệt (không gộp phẳng thành 1 đoạn text liên tục) - Excerpt nào có "score" (khác
// null) là Excerpt đã khớp trực tiếp với câu hỏi, được đánh dấu nổi bật hơn.
function ExcerptsView({ clause }: { clause: ClauseItem }) {
  const excerpts = clause.excerpts?.length ? clause.excerpts : [{ chunk_index: 0, text: clause.text || "", score: null }];
  return (
    <>
      {excerpts.map((ex, i) => {
        const matched = ex.score !== null && ex.score !== undefined;
        const html = marked.parse(ex.text || "", { async: false }) as string;
        return (
          <div
            key={i}
            className={`relative px-2.5 py-2 my-1.5 rounded-r-md border-l-[3px] ${
              matched ? "border-accent bg-accent-tint" : "border-border"
            }`}
          >
            {matched && (
              <span className="inline-block text-[0.68rem] font-semibold text-accent-dark bg-accent/12 rounded-full px-2 py-0.5 mb-1">
                matched · {ex.score}
              </span>
            )}
            <div className="markdown-body text-[0.79rem] leading-relaxed" dangerouslySetInnerHTML={{ __html: html }} />
          </div>
        );
      })}
    </>
  );
}

function EvidenceItem({ group, defaultOpen }: { group: ClauseGroup; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`border rounded-xl mb-2.5 overflow-hidden transition-colors ${open ? "border-accent/25 shadow-sm" : "border-border"}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left text-xs transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent-tint ${
          open ? "bg-accent-tint border-b border-border" : "bg-black/2"
        }`}
      >
        <span className="shrink-0 min-w-7 h-7 rounded-md bg-accent-tint text-accent-dark font-bold text-xs flex items-center justify-center">
          {group.article_number}
        </span>
        <div className="flex-1 min-w-0 flex flex-col gap-0.5">
          {group.article_title && <span className="font-semibold truncate">{group.article_title}</span>}
        </div>
        <span className="shrink-0 font-medium text-[0.72rem] text-muted bg-black/5 rounded-full px-2 py-0.5">{scoreLabel(group.score)}</span>
        <span className={`shrink-0 text-base transition-transform ${open ? "-rotate-90 text-accent" : "rotate-90 text-muted"}`}>&#8250;</span>
      </button>
      {open && (
        <div className="text-[0.79rem] leading-relaxed px-3.5 pt-2.5 pb-3.5">
          {group.clauses.map((c, i) => (
            <ExcerptsView key={i} clause={c} />
          ))}
        </div>
      )}
    </div>
  );
}

// "inline" = chỉ render danh sách (không tự bọc <aside>/header) - dùng khi đã có wrapper riêng lo
// phần khung/tab (xem EvidenceAside.tsx). Không truyền "inline" giữ nguyên hành vi cũ (đứng độc lập).
export default function EvidencePanel({ groups, inline }: { groups: ClauseGroup[] | null; inline?: boolean }) {
  const list = !groups || groups.length === 0 ? (
    <div className="text-muted text-sm leading-relaxed">Click "View citation" on a result to see the full content here.</div>
  ) : (
    groups.map((g, i) => <EvidenceItem key={i} group={g} defaultOpen={i === 0} />)
  );

  if (inline) return <>{list}</>;

  return (
    <aside className="w-[30rem] shrink-0 flex flex-col border border-border rounded-2xl bg-white overflow-hidden max-[1100px]:hidden">
      <div className="h-[4.5rem] shrink-0 px-4 flex items-center border-b border-border">
        <h3 className="text-xs uppercase tracking-wider text-muted m-0">Evidence</h3>
      </div>
      <div className="flex-1 overflow-y-auto p-4">{list}</div>
    </aside>
  );
}
