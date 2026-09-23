"use client";

import type { ReactNode } from "react";

import type { CodeFileDetail } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { ConfidenceBadge } from "./confidence";

function Heading({ children, count }: { children: ReactNode; count: number }) {
  return (
    <h4 className="flex items-center justify-between px-4 pt-4 pb-1.5 text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
      {children}
      <span className="tabular-nums">{count}</span>
    </h4>
  );
}

interface ModulePanelProps {
  detail: CodeFileDetail;
  onOpenFile: (path: string) => void;
}

/** Imports (with resolution), exports and statically detected API calls of one file. */
export function ModulePanel({ detail, onOpenFile }: ModulePanelProps) {
  const exports = detail.metadata.exports ?? [];
  const apiCalls = detail.metadata.api_calls ?? [];

  return (
    <div className="pb-4">
      {detail.metadata.docstring && (
        <p className="border-b border-slate-100 px-4 py-3 text-sm whitespace-pre-line text-slate-700">
          {detail.metadata.docstring}
        </p>
      )}

      <Heading count={detail.imports.length}>Imports</Heading>
      {detail.imports.length === 0 && <p className="px-4 text-sm text-slate-500">No imports.</p>}
      <ul className="divide-y divide-slate-100">
        {detail.imports.map((item) => {
          const names = item.names.map((name) =>
            name.alias && name.name !== "default" && name.name !== "*" ? `${name.name} as ${name.alias}` : (name.alias ?? name.name),
          );
          return (
            <li key={item.id} className="px-4 py-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-slate-900" title={item.module}>
                  {item.module}
                </span>
                <span className="text-slate-400">L{item.start_line}</span>
              </div>
              {names.length > 0 && (
                <p className="mt-0.5 truncate font-mono text-slate-500" title={names.join(", ")}>
                  {names.join(", ")}
                </p>
              )}
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="text-slate-400">
                  {item.kind.replace("_", " ")}
                  {item.is_type_only ? " · type only" : ""}
                </span>
                {item.resolution_status === "resolved" && item.resolved_path && (
                  <>
                    <button
                      type="button"
                      onClick={() => onOpenFile(item.resolved_path!)}
                      className="min-w-0 truncate font-mono text-indigo-600 hover:underline"
                    >
                      → {item.resolved_path}
                    </button>
                    {item.metadata.confidence && <ConfidenceBadge confidence={item.metadata.confidence} />}
                  </>
                )}
                {item.resolution_status === "external" && (
                  <span className="rounded bg-slate-100 px-1.5 py-px text-slate-600">
                    package {item.metadata.package ?? item.module}
                  </span>
                )}
                {item.resolution_status === "unresolved" && (
                  <span className="rounded bg-amber-50 px-1.5 py-px text-amber-800">not found in repository</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <Heading count={exports.length}>Exports</Heading>
      {exports.length === 0 ? (
        <p className="px-4 text-sm text-slate-500">Nothing exported.</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5 px-4">
          {exports.map((item, index) => (
            <li
              key={`${item.name}-${item.kind}-${index}`}
              className={cn(
                "rounded px-1.5 py-0.5 font-mono text-xs",
                item.kind === "re_export" || item.kind === "namespace" ? "bg-sky-50 text-sky-800" : "bg-slate-100 text-slate-700",
              )}
              title={item.source ? `re-exported from ${item.source}` : item.kind}
            >
              {item.name === "default" && item.local_name ? `default (${item.local_name})` : item.name}
            </li>
          ))}
        </ul>
      )}

      {apiCalls.length > 0 && (
        <>
          <Heading count={apiCalls.length}>API calls</Heading>
          <ul className="space-y-1 px-4">
            {apiCalls.map((call) => (
              <li key={`${call.line}-${call.url}`} className="font-mono text-xs text-slate-700">
                <span className="font-semibold">{call.method}</span> {call.url}
                <span className="ml-2 font-sans text-slate-400">
                  {call.client} · L{call.line}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
