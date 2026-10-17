import { BoundaryNode, DecisionNode, EndNode, FlowNode, GotoNode, OutputNode, RoutedEdge, TriggerNode, WaitNode } from "./nodes";

/** The map's shapes and lines, by the type each node and edge says it is. */
export const nodeTypes = {
  goto: GotoNode,
  flow: FlowNode,
  boundary: BoundaryNode,
  trigger: TriggerNode,
  result: OutputNode,
  decision: DecisionNode,
  wait: WaitNode,
  end: EndNode,
};

export const edgeTypes = { routed: RoutedEdge };
