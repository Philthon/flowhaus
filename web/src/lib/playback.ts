import type { FlowMap, Run } from "@/lib/api";

/**
 * Stepping through a recorded run, one box at a time. Nothing runs: it replays what the run already recorded, so the
 * map fills in as the run did and the panel below shows each step's items before and after.
 */

/** The boxes on this level that took part in the run, in the order items went through them. */
export function playOrder(map: FlowMap, run: Run | null, levelId: string): string[] {
  const level = map.levels[levelId];
  if (!run || !level) return [];
  const ids = level.children;
  const ran = (id: string) => ((map.groups.some((g) => g.id === id) ? run.groups[id] : run.nodes[id])?.status ?? "not_run") !== "not_run";
  // order by the lines between them (a box comes after everything that leads to it); ties keep the config order
  const into = new Map(ids.map((id) => [id, 0]));
  for (const e of level.edges) if (into.has(e.target) && into.has(e.source) && e.source !== e.target) into.set(e.target, into.get(e.target)! + 1);
  const order: string[] = [];
  const ready = ids.filter((id) => into.get(id) === 0);
  const seen = new Set<string>();
  while (ready.length) {
    const id = ready.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    for (const e of level.edges)
      if (e.source === id && into.has(e.target)) {
        into.set(e.target, into.get(e.target)! - 1);
        if (into.get(e.target) === 0) ready.push(e.target);
      }
  }
  for (const id of ids) if (!seen.has(id)) order.push(id); // loops: whatever is left, in config order
  return order.filter(ran);
}

/** Everything inside a group (its sub-groups and steps), for hiding a whole box that hasn't run yet. */
function inside(map: FlowMap, groupId: string): string[] {
  const groups = new Set([groupId]);
  for (let grew = true; grew; ) {
    grew = false;
    for (const g of map.groups)
      if (g.parent && groups.has(g.parent) && !groups.has(g.id)) {
        groups.add(g.id);
        grew = true;
      }
  }
  return [...groups, ...map.steps.filter((s) => s.group && groups.has(s.group)).map((s) => s.id)];
}

/** The boxes still to come after `order[index]` (with everything inside them): shown dimmed while stepping through. */
export function laterThan(map: FlowMap, order: string[], index: number): Set<string> {
  return new Set(order.slice(index + 1).flatMap((id) => [id, ...inside(map, id)]));
}
