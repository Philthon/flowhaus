import { cn } from "@/lib/utils";

/** Big flat page title with a Bauhaus shape marker. */
export function PageTitle({ shape, children, className }: { shape: "square" | "circle" | "triangle"; children: React.ReactNode; className?: string }) {
  return (
    <h1 className={cn("flex items-center gap-2.5 text-2xl font-medium tracking-tight", className)}>
      {shape === "square" && <span className="size-3 bg-red-500" aria-hidden />}
      {shape === "circle" && <span className="size-3 rounded-full bg-sky-500" aria-hidden />}
      {shape === "triangle" && (
        <svg viewBox="0 0 20 18" className="size-3.5" aria-hidden>
          <path d="M10 0 L20 18 L0 18 Z" fill="var(--bauhaus-yellow)" />
        </svg>
      )}
      {children}
    </h1>
  );
}
