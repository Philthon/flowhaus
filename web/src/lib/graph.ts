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

/**
 * The steps after the given ones, following the map's lines, in the order the steps are listed: what a change there
 * can reach. (The server's `review.downstream` walks the same way.)
 */
export function downstreamOf(order: string[], edges: { source: string; target: string }[], start: string[]): string[] {
  const seen = new Set(start);
  const queue = [...start];
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of edges)
      if (e.source === id && !seen.has(e.target)) {
        seen.add(e.target);
        queue.push(e.target);
      }
  }
  return order.filter((id) => seen.has(id) && !start.includes(id));
}
