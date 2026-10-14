// Adapted from AI Elements by Vercel (https://github.com/vercel/ai-elements), Apache-2.0.
// Modified for Flowhaus. License and changes: ./LICENSE
import type { ReactFlowProps } from "@xyflow/react";
import { Background, BackgroundVariant, ReactFlow } from "@xyflow/react";
import type { ReactNode } from "react";

import "@xyflow/react/dist/style.css";

type CanvasProps = ReactFlowProps & {
  children?: ReactNode;
};

const deleteKeyCode = ["Backspace", "Delete"];

export const Canvas = ({ children, ...props }: CanvasProps) => (
  <ReactFlow
    deleteKeyCode={deleteKeyCode}
    fitView
    panOnDrag={false}
    panOnScroll
    selectionOnDrag={true}
    zoomOnDoubleClick={false}
    {...props}
  >
    <Background bgColor="var(--sidebar)" variant={BackgroundVariant.Dots} gap={24} size={1} color="color-mix(in srgb, var(--foreground) 10%, transparent)" />
    {children}
  </ReactFlow>
);
