import type { AnalysisSummary } from "@/lib/api/types";
import { formatNumber } from "@/lib/utils";

const kindLabels: Record<string, string> = {
  function: "Functions",
  method: "Methods",
  class: "Classes",
  component: "Components",
  interface: "Interfaces",
  type_alias: "Types",
  enum: "Enums",
  variable: "Constants",
};

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-4 py-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-900 tabular-nums">{formatNumber(value)}</p>
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}

interface AnalysisOverviewProps {
  summary: AnalysisSummary;
  onOpenFile?: (path: string) => void;
}

/** Repository-wide numbers from code analysis: symbols, dependencies, hubs, packages. */
export function AnalysisOverview({ summary, onOpenFile }: AnalysisOverviewProps) {
  const totalSymbols = Object.values(summary.symbols_by_kind).reduce((sum, count) => sum + (count ?? 0), 0);
  const imports = summary.relationships.imports ?? { confirmed: 0, inferred: 0 };
  const symbolEdges = (["calls", "renders", "inherits"] as const).reduce(
    (sum, type) => sum + (summary.relationships[type]?.inferred ?? 0) + (summary.relationships[type]?.confirmed ?? 0),
    0,
  );
  const failed = (summary.parse_status.failed ?? 0) + (summary.parse_status.partial ?? 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Files parsed" value={summary.files_analyzed} hint={failed ? `${failed} parsed partially` : undefined} />
        <Stat label="Symbols" value={totalSymbols} />
        <Stat label="File imports" value={imports.confirmed + imports.inferred} hint={`${formatNumber(imports.confirmed)} confirmed`} />
        <Stat label="Calls & renders" value={symbolEdges} hint="inferred by name" />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <section>
          <h3 className="text-sm font-semibold text-slate-900">Symbols</h3>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {Object.entries(summary.symbols_by_kind).map(([kind, count]) => (
              <div key={kind} className="flex justify-between">
                <dt className="text-slate-500">{kindLabels[kind] ?? kind}</dt>
                <dd className="text-slate-900 tabular-nums">{formatNumber(count ?? 0)}</dd>
              </div>
            ))}
          </dl>
          <h3 className="mt-5 text-sm font-semibold text-slate-900">Languages parsed</h3>
          <p className="mt-1 text-sm text-slate-600">
            {Object.entries(summary.files_by_language)
              .map(([language, count]) => `${language} (${formatNumber(count)})`)
              .join(" · ") || "None"}
          </p>
        </section>

        <section>
          <h3 className="text-sm font-semibold text-slate-900">Most imported files</h3>
          {summary.most_imported.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">No internal imports found.</p>
          ) : (
            <ol className="mt-2 space-y-1">
              {summary.most_imported.slice(0, 8).map((item) => (
                <li key={item.path} className="flex items-center justify-between gap-3 text-sm">
                  {onOpenFile ? (
                    <button
                      type="button"
                      onClick={() => onOpenFile(item.path)}
                      className="min-w-0 truncate font-mono text-xs text-indigo-600 hover:underline"
                      title={item.path}
                    >
                      {item.path}
                    </button>
                  ) : (
                    <span className="min-w-0 truncate font-mono text-xs text-slate-700" title={item.path}>
                      {item.path}
                    </span>
                  )}
                  <span className="shrink-0 text-xs text-slate-500 tabular-nums">
                    {item.importers} {item.importers === 1 ? "importer" : "importers"}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      {summary.external_packages.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-900">External packages</h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {summary.external_packages.map((item) => (
              <span
                key={item.name}
                className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700"
                title={`Imported by ${item.files} file(s)`}
              >
                {item.name}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
