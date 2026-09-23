"use client";

import { type ReactNode, useMemo, useState } from "react";

import type { CodeFileSummary } from "@/lib/api/types";
import { cn, formatNumber } from "@/lib/utils";

interface DirectoryNode {
  name: string;
  path: string;
  directories: Map<string, DirectoryNode>;
  files: CodeFileSummary[];
}

function buildTree(files: CodeFileSummary[]): DirectoryNode {
  const root: DirectoryNode = { name: "", path: "", directories: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      const path = node.path ? `${node.path}/${part}` : part;
      let child = node.directories.get(part);
      if (!child) {
        child = { name: part, path, directories: new Map(), files: [] };
        node.directories.set(part, child);
      }
      node = child;
    }
    node.files.push(file);
  }
  return root;
}

function isAncestor(directory: string, path: string | null): boolean {
  return Boolean(path && path.startsWith(`${directory}/`));
}

interface FileTreeProps {
  files: CodeFileSummary[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

export function FileTree({ files, selectedPath, onSelect }: FileTreeProps) {
  const [filter, setFilter] = useState("");
  const [analyzedOnly, setAnalyzedOnly] = useState(false);
  // Directories the user explicitly opened/closed; others open when they contain the selection.
  const [toggled, setToggled] = useState<Map<string, boolean>>(new Map());

  const visibleFiles = useMemo(
    () => (analyzedOnly ? files.filter((file) => file.analyzed) : files),
    [files, analyzedOnly],
  );
  const tree = useMemo(() => buildTree(visibleFiles), [visibleFiles]);
  const query = filter.trim().toLowerCase();
  const matches = useMemo(
    () => (query ? visibleFiles.filter((file) => file.path.toLowerCase().includes(query)).slice(0, 300) : []),
    [visibleFiles, query],
  );

  // Small repositories start with top-level folders open; larger ones start collapsed.
  const openTopLevel = visibleFiles.length <= 60;
  const isOpen = (directory: DirectoryNode, depth: number) =>
    toggled.get(directory.path) ?? (isAncestor(directory.path, selectedPath) || (depth === 0 && openTopLevel));

  const toggle = (directory: DirectoryNode, depth: number) =>
    setToggled((current) => new Map(current).set(directory.path, !isOpen(directory, depth)));

  function renderFile(file: CodeFileSummary, depth: number, label: string) {
    const selected = file.path === selectedPath;
    return (
      <li key={file.path}>
        <button
          type="button"
          onClick={() => onSelect(file.path)}
          title={file.path}
          aria-current={selected ? "true" : undefined}
          className={cn(
            "flex w-full items-center gap-2 rounded px-2 py-0.5 text-left text-[13px]",
            selected ? "bg-indigo-50 text-indigo-800" : "hover:bg-slate-100",
            !file.analyzed && !selected && "text-slate-500",
          )}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <span className="min-w-0 flex-1 truncate font-mono">{label}</span>
          {file.analyzed && file.symbol_count > 0 && (
            <span className="shrink-0 text-[11px] text-slate-400 tabular-nums">{file.symbol_count}</span>
          )}
        </button>
      </li>
    );
  }

  function renderDirectory(directory: DirectoryNode, depth: number): ReactNode {
    const directories = [...directory.directories.values()].sort((a, b) => a.name.localeCompare(b.name));
    const children = (
      <>
        {directories.map((child) => {
          const open = isOpen(child, depth);
          return (
            <li key={child.path}>
              <button
                type="button"
                onClick={() => toggle(child, depth)}
                aria-expanded={open}
                className="flex w-full items-center gap-1.5 rounded px-2 py-0.5 text-left text-[13px] text-slate-700 hover:bg-slate-100"
                style={{ paddingLeft: `${depth * 12 + 4}px` }}
              >
                <span aria-hidden="true" className="w-3 text-[10px] text-slate-400">
                  {open ? "▾" : "▸"}
                </span>
                <span className="truncate font-mono">{child.name}</span>
              </button>
              {open && <ul>{renderDirectory(child, depth + 1)}</ul>}
            </li>
          );
        })}
        {directory.files.map((file) => renderFile(file, depth, file.path.split("/").pop() ?? file.path))}
      </>
    );
    return depth === 0 ? <ul>{children}</ul> : children;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-slate-100 p-3">
        <input
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter files…"
          aria-label="Filter files"
          className="block w-full rounded-md border-0 px-2.5 py-1.5 text-sm ring-1 ring-slate-300 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-600 focus:outline-none"
        />
        <label className="flex items-center justify-between gap-2 text-xs text-slate-500">
          <span className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={analyzedOnly}
              onChange={(event) => setAnalyzedOnly(event.target.checked)}
              className="size-3.5 rounded border-slate-300"
            />
            Parsed source files only
          </span>
          <span className="tabular-nums">{formatNumber(visibleFiles.length)} files</span>
        </label>
      </div>
      <nav aria-label="Repository files" className="min-h-0 flex-1 overflow-auto p-2">
        {query ? (
          matches.length ? (
            <ul>{matches.map((file) => renderFile(file, 0, file.path))}</ul>
          ) : (
            <p className="px-2 py-4 text-sm text-slate-500">No files match “{filter}”.</p>
          )
        ) : (
          renderDirectory(tree, 0)
        )}
      </nav>
    </div>
  );
}
