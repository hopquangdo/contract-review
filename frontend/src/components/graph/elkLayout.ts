import ELK from "elkjs/lib/elk.bundled.js";
import type { Edge, Node } from "@xyflow/react";
import type { FullGraphEdge, FullGraphNode } from "../../types";

// ELK.js (Eclipse Layout Kernel, port sang JS qua elkjs) - thuật toán layout graph CHUẨN PRODUCTION.
// Dùng "mrtree" (Multi-Root Tree) - thuật toán ELK thiết kế RIÊNG cho sơ đồ cây phân cấp/phân rã
// chức năng (functional decomposition/org chart): mỗi node xếp đúng 1 hàng theo độ sâu, con dàn
// đều ngang dưới cha, tự đảm bảo KHÔNG đè/chồng node (khác "radial" cũ hay dồn node khi nhiều nhánh
// cùng lúc chen vào 1 cung góc hẹp).
const elk = new ELK();

const ALGORITHM_ID = "org.eclipse.elk.mrtree";

export const NODE_WIDTH = 150;
export const CENTER_NODE_WIDTH = 180;
export const NODE_HEIGHT = 40;

// "mrtree" yêu cầu đồ thị đưa vào là CÂY THUẦN (mỗi node đúng 1 cha) - chỉ các quan hệ PHÂN CẤP
// (chứa/thuộc về) mới tạo thành cây hợp lệ. Các quan hệ THAM CHIẾU CHÉO (REFERS_TO/DEPENDS_ON/
// EXCEPTION_TO/REFERS_TO_APPENDIX/DEFINES) có thể khiến 1 node có NHIỀU cha hoặc tạo vòng lặp - nếu
// đưa hết vào ELK sẽ làm mrtree lỗi/treo (Promise không bao giờ resolve). Chỉ dùng quan hệ phân cấp
// để TÍNH VỊ TRÍ, các quan hệ còn lại vẫn được trả về nguyên vẹn để vẽ (dạng nét đứt đè lên trên).
const HIERARCHY_RELATIONS = new Set(["HAS_SECTION", "HAS_CLAUSE", "HAS_PARTY", "GOVERNED_BY", "HAS_DISPUTE_RULE"]);

export async function elkGraphLayout(fullNodes: FullGraphNode[], fullEdges: FullGraphEdge[]): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": ALGORITHM_ID,
      "elk.direction": "DOWN",
      "elk.spacing.nodeNode": "150",
      "elk.mrtree.spacing.nodeNodeBetweenLayers": "220",
    },
    children: fullNodes.map((n) => ({
      id: n.id,
      width: n.type === "Contract" ? CENTER_NODE_WIDTH : NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
    edges: fullEdges
      .filter((e) => HIERARCHY_RELATIONS.has(e.relation))
      .map((e, i) => ({ id: `elke${i}`, sources: [e.source], targets: [e.target] })),
  };

  const result = await elk.layout(elkGraph);
  const posById = new Map((result.children || []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]));

  const nodes: Node[] = fullNodes.map((n) => ({
    id: n.id,
    type: "fullGraphNode",
    position: posById.get(n.id) || { x: 0, y: 0 },
    data: { ...n, depth: 0 } as unknown as Record<string, unknown>,
  }));

  const edges: Edge[] = fullEdges.map((e, i) => ({
    id: `${e.source}->${e.target}:${e.relation}:${i}`,
    source: e.source,
    target: e.target,
    data: { relation: e.relation },
  }));

  return { nodes, edges };
}
