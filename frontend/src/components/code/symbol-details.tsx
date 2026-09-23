"use client";

import type { ReactNode } from "react";

import { LoadingState } from "@/components/ui/states";
import type { CodeSymbol, Page, Relationship } from "@/lib/api/types";
import type { ApiState } from "@/lib/hooks/use-api";

import { ConfidenceBadge } from "./confidence";
import { SymbolKindBadge, lineRange } from "./symbol-kind";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">{title}</h4>
      <div className="mt-1.5">{children}</div>
    </section>
  );
}

function Chips({ values }: { values: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        <span key={value} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
          {value}
        </span>
      ))}
    </div>
  );
}

interface SymbolDetailsProps {
  symbol: CodeSymbol;
  /** Calls/renders/inherits edges touching this symbol (fetched by the explorer). */
  edges: ApiState<Page<Relationship> | null>;
  onNavigate: (path: string, symbolId: string | null) => void;
}

export function SymbolDetails({ symbol, edges, onNavigate }: SymbolDetailsProps) {
  const flags = [
    symbol.is_exported && "exported",
    symbol.is_async && "async",
    typeof symbol.metadata.method_type === "string" && `${symbol.metadata.method_type}method`,
    symbol.metadata.static === true && "static",
    symbol.metadata.default_export === true && "default export",
    symbol.metadata.react_hook === true && "React hook",
  ].filter((flag): flag is string => Boolean(flag));

  const items = edges.status === "success" && edges.data ? edges.data.items : [];
  const outgoing = items.filter((edge) => edge.source_symbol?.id === symbol.id);
  const incoming = items.filter((edge) => edge.target_symbol?.id === symbol.id);

  return (
    <div className="space-y-4 border-b border-slate-100 bg-slate-50/60 px-4 py-4">
      <div>
        <div className="flex items-center gap-2">
          <SymbolKindBadge kind={symbol.kind} />
          <h3 className="min-w-0 truncate font-mono text-sm font-semibold text-slate-900">{symbol.qualified_name}</h3>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {lineRange(symbol.start_line, symbol.end_line)}
          {flags.length > 0 && ` · ${flags.join(" · ")}`}
        </p>
      </div>

      {symbol.signature && (
        <pre className="overflow-x-auto rounded-md bg-white px-3 py-2 font-mono text-xs whitespace-pre-wrap text-slate-800 ring-1 ring-slate-200">
          {symbol.signature}
        </pre>
      )}
      {(symbol.docstring || symbol.metadata.comment) && (
        <p className="text-sm whitespace-pre-line text-slate-700">{symbol.docstring ?? symbol.metadata.comment}</p>
      )}

      {symbol.parameters.length > 0 && (
        <Section title="Parameters">
          <table className="w-full text-xs">
            <tbody>
              {symbol.parameters.map((parameter) => (
                <tr key={`${parameter.name}-${parameter.kind}`} className="align-top">
                  <td className="py-0.5 pr-2 font-mono text-slate-900">
                    {parameter.kind === "rest" || parameter.kind === "var_positional" ? "…" : ""}
                    {parameter.name}
                    {parameter.optional ? "?" : ""}
                  </td>
                  <td className="py-0.5 pr-2 font-mono text-slate-600">{parameter.type ?? ""}</td>
                  <td className="py-0.5 text-slate-500">
                    {parameter.default != null && <span className="font-mono">= {parameter.default}</span>}
                    {!["positional", "rest", "var_positional"].includes(parameter.kind) && (
                      <span className="ml-1 text-slate-400">({parameter.kind.replace("_", " ")})</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
      {symbol.return_type && (
        <Section title="Returns">
          <span className="font-mono text-xs text-slate-800">{symbol.return_type}</span>
        </Section>
      )}
      {symbol.decorators.length > 0 && (
        <Section title="Decorators">
          <Chips values={symbol.decorators.map((decorator) => `@${decorator}`)} />
        </Section>
      )}
      {symbol.metadata.bases && symbol.metadata.bases.length > 0 && (
        <Section title="Extends">
          <Chips values={symbol.metadata.bases} />
        </Section>
      )}
      {symbol.metadata.hooks && symbol.metadata.hooks.length > 0 && (
        <Section title="React hooks">
          <Chips values={symbol.metadata.hooks} />
        </Section>
      )}
      {symbol.metadata.api_calls && symbol.metadata.api_calls.length > 0 && (
        <Section title="API calls">
          <ul className="space-y-1">
            {symbol.metadata.api_calls.map((call) => (
              <li key={`${call.line}-${call.url}`} className="font-mono text-xs text-slate-700">
                <span className="font-semibold">{call.method}</span> {call.url}
                <span className="ml-2 font-sans text-slate-400">L{call.line}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Relationships">
        {edges.status === "loading" && <LoadingState label="Loading relationships…" />}
        {edges.status === "error" && <p className="text-xs text-rose-700">{edges.error.message}</p>}
        {edges.status === "success" && incoming.length + outgoing.length === 0 && (
          <p className="text-xs text-slate-500">No resolved calls, renders or inheritance for this symbol.</p>
        )}
        {edges.status === "success" && (
          <div className="space-y-3">
            <EdgeList title="Uses" edges={outgoing} side="target" onNavigate={onNavigate} />
            <EdgeList title="Used by" edges={incoming} side="source" onNavigate={onNavigate} />
          </div>
        )}
      </Section>
    </div>
  );
}

function EdgeList({
  title,
  edges,
  side,
  onNavigate,
}: {
  title: string;
  edges: Relationship[];
  side: "source" | "target";
  onNavigate: (path: string, symbolId: string | null) => void;
}) {
  if (edges.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium text-slate-600">{title}</p>
      <ul className="mt-1 space-y-1">
        {edges.map((edge) => {
          const other = side === "target" ? edge.target_symbol : edge.source_symbol;
          const path = side === "target" ? edge.target_path : edge.source_path;
          return (
            <li key={edge.id}>
              <button
                type="button"
                onClick={() => onNavigate(path, other?.id ?? null)}
                className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-white"
                title={`${edge.relationship_type} · resolved via ${edge.metadata.resolution ?? "?"} · ${path}`}
              >
                <span className="w-14 shrink-0 text-slate-400">{edge.relationship_type}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-slate-800">{other?.qualified_name}</span>
                <ConfidenceBadge confidence={edge.confidence} />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
