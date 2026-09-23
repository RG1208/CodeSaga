"use client";

import { useEffect, useRef } from "react";

import { ErrorState, LoadingState } from "@/components/ui/states";
import { codeApi } from "@/lib/api/endpoints";
import { useApi } from "@/lib/hooks/use-api";
import { cn, formatBytes, formatNumber } from "@/lib/utils";

const MAX_RENDERED_LINES = 5000;

interface SourceViewerProps {
  repositoryId: string;
  path: string;
  highlight: { start: number; end: number } | null;
}

/** Plain-text source with line numbers; the selected symbol's line range is highlighted. */
export function SourceViewer({ repositoryId, path, highlight }: SourceViewerProps) {
  const content = useApi(`code:content:${repositoryId}:${path}`, (signal) =>
    codeApi.content(repositoryId, path, { signal }),
  );
  const firstHighlighted = useRef<HTMLDivElement | null>(null);
  const loaded = content.status === "success";

  useEffect(() => {
    if (loaded && highlight) {
      // Instant: smooth scrolling across thousands of lines is slow and can be interrupted.
      firstHighlighted.current?.scrollIntoView({ block: "center" });
    }
  }, [loaded, highlight]);

  if (content.status === "loading") return <LoadingState label="Loading file…" />;
  if (content.status === "error") {
    return <ErrorState title="Could not open file" error={content.error} onRetry={content.reload} />;
  }

  const lines = content.data.content.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const shown = lines.slice(0, MAX_RENDERED_LINES);
  const gutterWidth = `${String(shown.length).length + 1}ch`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
        <span className="font-mono text-sm font-medium text-slate-900">{path}</span>
        <span>{content.data.language ?? "Plain text"}</span>
        <span>{formatNumber(content.data.line_count)} lines</span>
        <span>{formatBytes(content.data.size_bytes)}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto bg-white py-2 font-mono text-[12.5px] leading-5" style={{ tabSize: 4 }}>
        {shown.map((line, index) => {
          const number = index + 1;
          const highlighted = highlight !== null && number >= highlight.start && number <= highlight.end;
          return (
            <div
              key={number}
              id={`L${number}`}
              ref={highlighted && number === highlight?.start ? firstHighlighted : undefined}
              className={cn("flex", highlighted && "bg-amber-50")}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "shrink-0 border-r pr-3 text-right text-slate-400 select-none",
                  highlighted ? "border-amber-400" : "border-transparent",
                )}
                style={{ width: gutterWidth, minWidth: gutterWidth }}
              >
                {number}
              </span>
              <span className="pr-4 pl-4 whitespace-pre text-slate-800">{line || " "}</span>
            </div>
          );
        })}
        {lines.length > MAX_RENDERED_LINES && (
          <p className="px-4 py-3 font-sans text-xs text-slate-500">
            Showing the first {formatNumber(MAX_RENDERED_LINES)} of {formatNumber(lines.length)} lines.
          </p>
        )}
      </div>
    </div>
  );
}
