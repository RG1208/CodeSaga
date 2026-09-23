"use client";

import { useEffect, useState } from "react";

import { codeApi } from "@/lib/api/endpoints";
import type { SymbolSearchResult } from "@/lib/api/types";
import { useApi } from "@/lib/hooks/use-api";

import { SymbolKindBadge } from "./symbol-kind";

interface SymbolSearchProps {
  repositoryId: string;
  onSelect: (symbol: SymbolSearchResult) => void;
}

export function SymbolSearch({ repositoryId, onSelect }: SymbolSearchProps) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(text.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [text]);

  const results = useApi(`code:symbol-search:${repositoryId}:${query}`, (signal) =>
    query.length >= 2 ? codeApi.searchSymbols(repositoryId, { q: query, limit: 12 }, { signal }) : Promise.resolve(null),
  );
  const items = results.status === "success" && results.data ? results.data.items : [];

  return (
    <div className="relative w-full sm:w-80">
      <input
        type="search"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        placeholder="Search symbols…"
        aria-label="Search symbols"
        className="block w-full rounded-lg border-0 bg-white px-3 py-1.5 text-sm ring-1 ring-slate-300 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-600 focus:outline-none"
      />
      {open && query.length >= 2 && (
        <div className="absolute right-0 z-30 mt-1 w-full min-w-[20rem] overflow-hidden rounded-lg bg-white shadow-lg ring-1 ring-slate-200">
          {results.status === "loading" || (results.isRefreshing && items.length === 0) ? (
            <p className="px-3 py-3 text-sm text-slate-500">Searching…</p>
          ) : results.status === "error" ? (
            <p className="px-3 py-3 text-sm text-rose-700">{results.error.message}</p>
          ) : items.length === 0 ? (
            <p className="px-3 py-3 text-sm text-slate-500">No symbols match “{query}”.</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto py-1">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    // mousedown fires before the input's blur closes the list
                    onMouseDown={(event) => {
                      event.preventDefault();
                      onSelect(item);
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50"
                  >
                    <SymbolKindBadge kind={item.kind} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-sm text-slate-900">{item.qualified_name}</span>
                      <span className="block truncate text-xs text-slate-500">
                        {item.file_path}:{item.start_line}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
