import type { SymbolKind } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const kindDisplay: Record<SymbolKind, { label: string; className: string }> = {
  function: { label: "fn", className: "bg-sky-50 text-sky-700 ring-sky-200" },
  method: { label: "method", className: "bg-sky-50 text-sky-700 ring-sky-200" },
  class: { label: "class", className: "bg-violet-50 text-violet-700 ring-violet-200" },
  component: { label: "component", className: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  interface: { label: "interface", className: "bg-amber-50 text-amber-800 ring-amber-200" },
  type_alias: { label: "type", className: "bg-amber-50 text-amber-800 ring-amber-200" },
  enum: { label: "enum", className: "bg-amber-50 text-amber-800 ring-amber-200" },
  variable: { label: "const", className: "bg-slate-100 text-slate-700 ring-slate-200" },
};

export function SymbolKindBadge({ kind }: { kind: SymbolKind }) {
  const { label, className } = kindDisplay[kind];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded px-1.5 py-px font-mono text-[10px] leading-4 font-medium ring-1 ring-inset",
        className,
      )}
    >
      {label}
    </span>
  );
}

export function lineRange(start: number, end: number): string {
  return start === end ? `L${start}` : `L${start}–${end}`;
}
