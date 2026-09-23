"use client";

import { useState } from "react";

import type { LanguageStat } from "@/lib/api/types";
import { cn, formatBytes, formatNumber } from "@/lib/utils";

/*
 * Part-to-whole → one stacked bar. Categorical slots in fixed order (validated:
 * adjacent CVD ΔE ≥ 9.1, normal-vision ΔE ≥ 19.6 on white). Slots 3–5 are below
 * 3:1 contrast, so the legend table always carries names and values as text.
 */
const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const OTHER_COLOR = "#898781";
const MAX_SEGMENTS = SERIES_COLORS.length;

interface Segment {
  label: string;
  files: number;
  bytes: number;
  share: number;
  color: string;
  /** Horizontal midpoint of the segment (0–1), used to place the tooltip. */
  center: number;
}

function toSegments(languages: LanguageStat[]): Segment[] {
  const shares = toShares(languages);
  return shares.map((segment, index) => {
    const start = shares.slice(0, index).reduce((sum, item) => sum + item.share, 0);
    return { ...segment, center: start + segment.share / 2 };
  });
}

function toShares(languages: LanguageStat[]): Omit<Segment, "center">[] {
  const total = languages.reduce((sum, item) => sum + item.bytes, 0);
  if (total === 0) return [];
  const needsOther = languages.length > MAX_SEGMENTS;
  const head = needsOther ? languages.slice(0, MAX_SEGMENTS - 1) : languages;
  const segments = head.map((item, index) => ({
    label: item.language,
    files: item.files,
    bytes: item.bytes,
    share: item.bytes / total,
    color: SERIES_COLORS[index],
  }));
  if (needsOther) {
    const rest = languages.slice(MAX_SEGMENTS - 1);
    const bytes = rest.reduce((sum, item) => sum + item.bytes, 0);
    segments.push({
      label: `Other (${rest.length})`,
      files: rest.reduce((sum, item) => sum + item.files, 0),
      bytes,
      share: bytes / total,
      color: OTHER_COLOR,
    });
  }
  return segments;
}

function percent(share: number): string {
  return share < 0.001 ? "<0.1%" : `${(share * 100).toFixed(1)}%`;
}

export function LanguageBreakdown({ languages }: { languages: LanguageStat[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const segments = toSegments(languages);

  if (segments.length === 0) {
    return <p className="text-sm text-slate-500">No recognized source files.</p>;
  }

  const positioned = segments;
  const active = hovered === null ? null : positioned[hovered];

  return (
    <div>
      <div className="relative pt-7">
        {active && (
          <div
            className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-md bg-slate-900 px-2 py-1 text-xs whitespace-nowrap text-white shadow"
            style={{ left: `${Math.min(92, Math.max(8, active.center * 100))}%` }}
          >
            {active.label} · {percent(active.share)} · {formatNumber(active.files)} files
          </div>
        )}
        {/* The 2px gap shows the card surface between segments. */}
        <div className="flex h-3 w-full gap-[2px]" aria-hidden="true">
          {positioned.map((segment, index) => (
            <div
              key={segment.label}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              className={cn(
                "h-full min-w-[3px] transition-opacity first:rounded-l last:rounded-r",
                hovered !== null && hovered !== index && "opacity-40",
              )}
              style={{ width: `${segment.share * 100}%`, backgroundColor: segment.color }}
            />
          ))}
        </div>
      </div>

      <table className="mt-4 w-full text-sm">
        <caption className="sr-only">Languages by share of source bytes</caption>
        <thead>
          <tr className="text-left text-xs text-slate-500">
            <th scope="col" className="pb-1 font-medium">Language</th>
            <th scope="col" className="pb-1 text-right font-medium">Share</th>
            <th scope="col" className="pb-1 text-right font-medium">Files</th>
            <th scope="col" className="pb-1 text-right font-medium">Size</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {positioned.map((segment, index) => (
            <tr
              key={segment.label}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              className={cn(hovered === index && "bg-slate-50")}
            >
              <td className="py-1 pr-2">
                <span className="flex items-center gap-2 text-slate-900">
                  <span
                    aria-hidden="true"
                    className="size-2.5 shrink-0 rounded-sm"
                    style={{ backgroundColor: segment.color }}
                  />
                  {segment.label}
                </span>
              </td>
              <td className="py-1 text-right text-slate-700">{percent(segment.share)}</td>
              <td className="py-1 text-right text-slate-500">{formatNumber(segment.files)}</td>
              <td className="py-1 text-right text-slate-500">{formatBytes(segment.bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
