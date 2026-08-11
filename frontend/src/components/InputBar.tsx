import { useRef, type KeyboardEvent, type ReactNode } from "react";

interface InputBarProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onAttach: (file: File) => void;
  attachedFile: File | null;
  onRemoveAttached: () => void;
  disabled: boolean;
  children?: ReactNode; // ContextRow (3 tiêu chí) - render bên trong CÙNG 1 khối nền trắng với ô nhập
}

export default function InputBar({ value, onChange, onSend, onAttach, attachedFile, onRemoveAttached, disabled, children }: InputBarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const autoGrow = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="shrink-0 border-t border-border bg-white px-4 pt-3 pb-4">
      {children}

      <div className="w-full max-w-[700px] mx-auto flex items-end gap-2 border border-border rounded-2xl bg-white px-2.5 py-2 shadow-[0_2px_8px_rgba(0,0,0,0.06)]">
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onAttach(f);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          title="Đính kèm checklist JSON"
          className="border-none bg-black/4 rounded-[10px] w-[38px] h-[38px] cursor-pointer text-base flex items-center justify-center text-muted hover:bg-black/8 shrink-0"
        >
          +
        </button>

        <div className="flex-1 flex flex-col min-w-0">
          {attachedFile && (
            <span className="text-[0.8rem] text-accent-dark bg-accent-tint rounded-full px-2.5 py-1 inline-flex items-center gap-1 self-start mb-1">
              {attachedFile.name}
              <button type="button" onClick={onRemoveAttached} className="border-none bg-transparent cursor-pointer text-accent-dark font-bold">
                x
              </button>
            </span>
          )}
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="Nhập mục cần kiểm tra về hợp đồng này..."
            value={value}
            disabled={disabled}
            onChange={(e) => {
              onChange(e.target.value);
              autoGrow();
            }}
            onKeyDown={handleKeyDown}
            className="w-full block border-none outline-none resize-none font-sans text-[0.95rem] leading-normal p-2 max-h-40 bg-transparent disabled:opacity-60"
          />
        </div>

        <button
          type="button"
          onClick={onSend}
          disabled={disabled}
          title="Gửi"
          className="border-none bg-accent text-white rounded-[10px] w-[38px] h-[38px] cursor-pointer text-base shrink-0 hover:bg-accent-dark disabled:opacity-40 disabled:cursor-default disabled:hover:bg-accent"
        >
          ↑
        </button>
      </div>
    </div>
  );
}
