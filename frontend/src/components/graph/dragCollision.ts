import type { Node } from "@xyflow/react";

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function rectsOverlap(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function nodeRect(n: Node, fallbackWidth: number, fallbackHeight: number): Rect {
  return {
    x: n.position.x,
    y: n.position.y,
    w: n.measured?.width ?? fallbackWidth,
    h: n.measured?.height ?? fallbackHeight,
  };
}

// Node vừa kéo có đè lên node khác không - dùng kích thước ĐÃ RENDER thật ("measured" của React
// Flow, tự đo sau khi mount) kèm fallback nếu chưa đo được kịp.
export function draggedNodeOverlapsAny(dragged: Node, allNodes: Node[], fallbackWidth: number, fallbackHeight: number): boolean {
  const a = nodeRect(dragged, fallbackWidth, fallbackHeight);
  return allNodes.some((n) => n.id !== dragged.id && rectsOverlap(a, nodeRect(n, fallbackWidth, fallbackHeight)));
}

// Tìm vị trí GẦN NHẤT không đè lên node nào khác, xuất phát từ vị trí người dùng vừa thả tay - mỗi
// vòng lặp đẩy node ra khỏi node đang đè NHIỀU NHẤT theo trục cần dịch chuyển ÍT NHẤT để thoát chồng
// lấn (trục x nếu độ chồng lấn theo x nhỏ hơn theo y, ngược lại đẩy theo y) - giống thuật toán tách
// AABB (axis-aligned bounding box) tối thiểu hoá dịch chuyển, dùng trong game 2D/vật lý va chạm đơn
// giản. Lặp tối đa MAX_ITERATIONS lần vì đẩy tách 1 node có thể tạo chồng lấn mới với node khác.
const MAX_ITERATIONS = 8;
const EPSILON = 1; // đẩy dư 1px để không còn chạm biên (tránh rectsOverlap coi 2 cạnh chạm nhau là vẫn đè)

export function findNearestValidPosition(
  dragged: Node,
  allNodes: Node[],
  fallbackWidth: number,
  fallbackHeight: number,
): { x: number; y: number } {
  const others = allNodes.filter((n) => n.id !== dragged.id).map((n) => nodeRect(n, fallbackWidth, fallbackHeight));
  const a: Rect = { ...nodeRect(dragged, fallbackWidth, fallbackHeight) };

  for (let iter = 0; iter < MAX_ITERATIONS; iter++) {
    // Chọn node đang đè NHIỀU NHẤT (diện tích chồng lấn lớn nhất) để ưu tiên tách trước - tách node
    // đè nặng nhất thường kéo theo tự hết đè các node nhẹ hơn ở vòng lặp sau.
    let worst: Rect | null = null;
    let worstArea = 0;
    for (const b of others) {
      if (!rectsOverlap(a, b)) continue;
      const overlapX = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      const area = overlapX * overlapY;
      if (area > worstArea) {
        worstArea = area;
        worst = b;
      }
    }
    if (!worst) break; // không còn đè node nào - đã tìm được vị trí hợp lệ

    const overlapX = Math.min(a.x + a.w, worst.x + worst.w) - Math.max(a.x, worst.x);
    const overlapY = Math.min(a.y + a.h, worst.y + worst.h) - Math.max(a.y, worst.y);
    const aCenterX = a.x + a.w / 2;
    const aCenterY = a.y + a.h / 2;
    const bCenterX = worst.x + worst.w / 2;
    const bCenterY = worst.y + worst.h / 2;

    // Đẩy theo trục có độ chồng lấn NHỎ HƠN - dịch chuyển ít nhất mà vẫn thoát đè, giữ vị trí mới
    // gần vị trí người dùng vừa thả nhất có thể.
    if (overlapX < overlapY) {
      const dir = aCenterX >= bCenterX ? 1 : -1;
      a.x += dir * (overlapX + EPSILON);
    } else {
      const dir = aCenterY >= bCenterY ? 1 : -1;
      a.y += dir * (overlapY + EPSILON);
    }
  }

  return { x: a.x, y: a.y };
}
