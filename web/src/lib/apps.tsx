import { Clock, FileText, Hand, Webhook, Zap } from "lucide-react";

import { cn } from "@/lib/utils";

/** Each app gets one flat marker color from the Bauhaus palette (brand-free). */
const APP_MARK: Record<string, string> = {
  Clay: "var(--bauhaus-yellow)",
  Firecrawl: "var(--bauhaus-red)",
  HubSpot: "var(--bauhaus-red)",
  Slack: "var(--bauhaus-blue)",
  Claude: "var(--bauhaus-yellow)",
  Typeform: "var(--foreground)",
  Stripe: "var(--bauhaus-blue)",
  Gmail: "var(--bauhaus-red)",
  Xero: "var(--bauhaus-blue)",
  Schedule: "var(--foreground)",
  Webhook: "var(--foreground)",
};

/** Outlined tag with a small colored square: which app a step talks to. */
export function AppBadge({ app, className }: { app: string; className?: string }) {
  const code = app === "Code" || app === "CSV file" || app === "Sample file";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 border border-foreground/25 px-1 py-px text-[11px] font-medium whitespace-nowrap text-foreground",
        className,
      )}
      title={app}
    >
      <span
        className={cn("size-2 shrink-0", code && "border border-foreground bg-transparent")}
        style={code ? undefined : { background: APP_MARK[app] ?? "var(--muted-foreground)" }}
        aria-hidden
      />
      {app}
    </span>
  );
}

export function TriggerIcon({ type, className }: { type: string; className?: string }) {
  const Icon = type === "schedule" ? Clock : type === "webhook" ? Webhook : type === "manual" ? Hand : type === "event" ? Zap : FileText;
  return <Icon className={cn("size-4", className)} />;
}
