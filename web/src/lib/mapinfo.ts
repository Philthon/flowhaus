import type { Counts, FlowMap, PrevCounts, Run, Status } from "@/lib/api";

/** The start and result boxes of the top level (not steps of the flow). */
export const INPUT_ID = "__input__";
export const OUTPUT_ID = "__output__";

export function nodeInfo(map: FlowMap, run: Run | null, id: string) {
  if (id === INPUT_ID || id === OUTPUT_ID) {
    const output = id === OUTPUT_ID;
    // In: fine as soon as items were read. Out: follows the run (failed run = nothing came out).
    const status: Status = !run ? "not_run" : output ? run.status : run.input_count ? "success" : run.status;
    return {
      previous: null,
      isGroup: false,
      kind: "action" as const,
      label: output ? "What came out" : "What came in",
      description: output ? (map.flow.output?.label ?? "The items that made it through") : map.flow.trigger.label,
      status,
      counts: null,
    };
  }
  const group = map.groups.find((g) => g.id === id);
  const step = map.steps.find((s) => s.id === id);
  const counts: (Counts & { failed_step?: string | null }) | null = group
    ? (run?.groups[id] ?? null)
    : (run?.nodes[id] ?? null);
  const previous: PrevCounts | null = (group ? run?.previous?.groups[id] : run?.previous?.nodes[id]) ?? null;
  return {
    previous,
    isGroup: !!group,
    kind: group ? "action" : (step?.kind ?? "action"),
    label: group?.label ?? step?.label ?? id,
    description: group?.description ?? step?.description ?? "",
    status: (counts?.status ?? "not_run") as Status,
    counts,
  };
}
