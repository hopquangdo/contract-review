// Kiểu dữ liệu UI-only để gộp 1 mục checklist gốc (ChecklistInputItem) với kết quả đánh giá của nó
// (SingleAnswer, từ /api/checklist-item/stream) - KHÔNG khớp trực tiếp response backend nào, chỉ để
// ChecklistPanel/App quản lý trạng thái chạy từng mục (pending/running/done/error).
import type { ChecklistInputItem, SingleAnswer } from "./types";

export type ReviewStatus = "pending" | "running" | "done" | "error";

export interface ReviewEntry {
  item: ChecklistInputItem;
  status: ReviewStatus;
  answer: SingleAnswer | null;
  errorMessage: string | null;
}
