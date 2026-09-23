"use client";

import type { CodeSymbol } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { SymbolKindBadge, lineRange } from "./symbol-kind";

interface SymbolOutlineProps {
  symbols: CodeSymbol[];
  selectedId: string | null;
  onSelect: (symbol: CodeSymbol) => void;
}

/** Symbols as a tree (classes contain methods), in source order. */
export function SymbolOutline({ symbols, selectedId, onSelect }: SymbolOutlineProps) {
  if (symbols.length === 0) {
    return <p className="px-4 py-6 text-sm text-slate-500">No functions, classes or types in this file.</p>;
  }
  const children = new Map<string | null, CodeSymbol[]>();
  for (const symbol of symbols) {
    const siblings = children.get(symbol.parent_symbol_id) ?? [];
    siblings.push(symbol);
    children.set(symbol.parent_symbol_id, siblings);
  }

  const renderLevel = (parentId: string | null, depth: number) => (
    <ul>
      {(children.get(parentId) ?? []).map((symbol) => (
        <li key={symbol.id}>
          <button
            type="button"
            onClick={() => onSelect(symbol)}
            aria-current={symbol.id === selectedId ? "true" : undefined}
            className={cn(
              "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px]",
              symbol.id === selectedId ? "bg-indigo-50 text-indigo-900" : "hover:bg-slate-100",
            )}
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
          >
            <SymbolKindBadge kind={symbol.kind} />
            <span className="min-w-0 flex-1 truncate font-mono">{symbol.name}</span>
            {symbol.is_exported && (
              <span className="shrink-0 text-[10px] font-medium text-emerald-700" title="Exported">
                export
              </span>
            )}
            <span className="shrink-0 text-[11px] text-slate-400 tabular-nums">
              {lineRange(symbol.start_line, symbol.end_line)}
            </span>
          </button>
          {children.has(symbol.id) && renderLevel(symbol.id, depth + 1)}
        </li>
      ))}
    </ul>
  );

  return <div className="p-2">{renderLevel(null, 0)}</div>;
}
