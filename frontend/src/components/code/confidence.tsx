import type { Confidence } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Text + line style (not colour alone) distinguish confirmed from inferred. */
export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded px-1.5 py-px text-[10px] font-medium",
        confidence === "confirmed"
          ? "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200 ring-inset"
          : "text-slate-600 ring-1 ring-slate-300 ring-inset [border-style:dashed]",
      )}
      title={
        confidence === "confirmed"
          ? "Confirmed: the import resolved to exactly one file."
          : "Inferred: matched by name; static analysis cannot prove it."
      }
    >
      {confidence}
    </span>
  );
}
