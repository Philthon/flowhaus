/** The app's pages and their URLs (hash routes, so the API serves one page). */
export type Route =
  | { page: "flows" }
  | { page: "activity"; flowId?: string }
  | { page: "connections" }
  | { page: "new" }
  | { page: "flow"; flowId: string; runId?: string };

export function parse(hash: string): Route {
  const [path, query] = hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query ?? "");
  const [page, id] = path.split("/");
  if (page === "flow" && id) return { page: "flow", flowId: id, runId: params.get("run") ?? undefined };
  if (page === "activity") return { page: "activity", flowId: params.get("flow") ?? undefined };
  if (page === "connections") return { page: "connections" };
  if (page === "new") return { page: "new" };
  return { page: "flows" };
}

export function href(route: Route): string {
  if (route.page === "flow") return `#/flow/${route.flowId}${route.runId ? `?run=${encodeURIComponent(route.runId)}` : ""}`;
  if (route.page === "activity") return `#/activity${route.flowId ? `?flow=${route.flowId}` : ""}`;
  if (route.page === "connections") return "#/connections";
  if (route.page === "new") return "#/new";
  return "#/flows";
}

export const go = (route: Route) => {
  window.location.hash = href(route);
};
