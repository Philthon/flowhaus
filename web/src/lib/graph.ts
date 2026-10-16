/** Lines that go back to a box already passed on the way there (found walking the map from its first boxes). */
export function loopEdges(children: string[], edges: { source: string; target: string }[]): Set<string> {
  const out = new Map<string, string[]>();
  for (const e of edges) out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
  const into = new Set(edges.map((e) => e.target));
  const state = new Map<string, "open" | "done">();
  const loops = new Set<string>();
  const visit = (id: string) => {
    state.set(id, "open");
    for (const t of out.get(id) ?? []) {
      if (state.get(t) === "open") loops.add(`${id}->${t}`);
      else if (!state.has(t)) visit(t);
    }
    state.set(id, "done");
  };
  for (const id of [...children.filter((c) => !into.has(c)), ...children]) if (!state.has(id)) visit(id);
  return loops;
}
