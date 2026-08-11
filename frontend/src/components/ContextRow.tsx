// Luôn hiển thị sẵn 3 trường này (không ẩn sau nút bấm) - để người dùng luôn nhớ điền tiêu chí
// Đạt/Vi phạm cho mỗi mục kiểm tra, không bỏ sót vì quên bấm nút mở. Giữ nguyên giá trị sau khi
// gửi (không tự xoá) - tiện khi hỏi liên tiếp nhiều câu dùng chung 1 bộ tiêu chí.
interface ContextRowProps {
  pass: string;
  violation: string;
  note: string;
  onPassChange: (v: string) => void;
  onViolationChange: (v: string) => void;
  onNoteChange: (v: string) => void;
}

interface FieldConfig {
  key: "pass" | "violation" | "note";
  label: string;
  placeholder: string;
  dotClass: string;
  value: string;
  onChange: (v: string) => void;
}

export default function ContextRow({ pass, violation, note, onPassChange, onViolationChange, onNoteChange }: ContextRowProps) {
  const fields: FieldConfig[] = [
    { key: "pass", label: "Đạt khi", placeholder: "Điều kiện để coi là đạt", dotClass: "bg-ok", value: pass, onChange: onPassChange },
    { key: "violation", label: "Vi phạm khi", placeholder: "Điều kiện để coi là vi phạm", dotClass: "bg-fail", value: violation, onChange: onViolationChange },
    { key: "note", label: "Lưu ý", placeholder: "Không bắt buộc", dotClass: "bg-neutral", value: note, onChange: onNoteChange },
  ];

  return (
    <div className="w-full max-w-[700px] mx-auto mb-2.5 grid grid-cols-3 gap-2 max-[700px]:grid-cols-1">
      {fields.map((f) => (
        <div key={f.key} className="flex flex-col gap-1">
          <label className="flex items-center gap-1.5 text-[0.72rem] font-semibold text-muted">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${f.dotClass}`} />
            {f.label}
          </label>
          <textarea
            rows={1}
            placeholder={f.placeholder}
            value={f.value}
            onChange={(e) => f.onChange(e.target.value)}
            className="border border-border rounded-lg px-2.5 py-1.5 font-sans text-[0.8rem] resize-y min-h-[2.3rem] bg-white outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent-tint"
          />
        </div>
      ))}
    </div>
  );
}
