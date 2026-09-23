"use client";

import { useState } from "react";

import type { Confidence } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export interface DiagramNode {
  key: string;
  label: string;
  sublabel?: string;
  title: string;
  confidence: Confidence;
  relation?: string; // e.g. "calls", "renders"
  onSelect?: () => void;
}

interface DependencyDiagramProps {
  center: { label: string; sublabel?: string };
  incoming: DiagramNode[];
  outgoing: DiagramNode[];
  incomingTitle: string;
  outgoingTitle: string;
  ariaLabel: string;
}

// Sized to render near 1:1 in the explorer's centre pane, so text stays readable.
const WIDTH = 600;
const NODE_WIDTH = 180;
const NODE_HEIGHT = 40;
const GAP = 10;
const HEADER = 26;
const CENTER_X = (WIDTH - NODE_WIDTH) / 2;
const RIGHT_X = WIDTH - NODE_WIDTH;
const MAX_NODES = 12;
const STROKE = { confirmed: "#4f46e5", inferred: "#64748b" } as const;

function truncateEnd(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function truncateStart(text: string, max: number): string {
  return text.length <= max ? text : `…${text.slice(text.length - max + 1)}`;
}

/** incoming → center → outgoing. Solid lines are confirmed edges; dashed lines are inferred. */
export function DependencyDiagram(props: DependencyDiagramProps) {
  const { center, incomingTitle, outgoingTitle, ariaLabel } = props;
  const [hovered, setHovered] = useState<string | null>(null);

  const limit = (nodes: DiagramNode[]) =>
    nodes.length > MAX_NODES
      ? {
          shown: nodes.slice(0, MAX_NODES - 1),
          more: nodes.length - (MAX_NODES - 1),
        }
      : { shown: nodes, more: 0 };
  const incoming = limit(props.incoming);
  const outgoing = limit(props.outgoing);
  const rows = Math.max(incoming.shown.length + (incoming.more ? 1 : 0), outgoing.shown.length + (outgoing.more ? 1 : 0), 1);
  const columnHeight = rows * (NODE_HEIGHT + GAP) - GAP;
  const height = HEADER + columnHeight + 4;
  const centerY = HEADER + columnHeight / 2 - NODE_HEIGHT / 2;

  const nodeY = (index: number, count: number) =>
    HEADER + ((rows - count) * (NODE_HEIGHT + GAP)) / 2 + index * (NODE_HEIGHT + GAP);

  const renderSide = (side: "in" | "out", nodes: { shown: DiagramNode[]; more: number }) => {
    const count = nodes.shown.length + (nodes.more ? 1 : 0);
    const x = side === "in" ? 0 : RIGHT_X;
    return (
      <g>
        {nodes.shown.map((node, index) => {
          const y = nodeY(index, count);
          const active = hovered === node.key;
          const [x1, y1, x2, y2] =
            side === "in"
              ? [NODE_WIDTH, y + NODE_HEIGHT / 2, CENTER_X, centerY + NODE_HEIGHT / 2]
              : [CENTER_X + NODE_WIDTH, centerY + NODE_HEIGHT / 2, RIGHT_X, y + NODE_HEIGHT / 2];
          const interactive = Boolean(node.onSelect);
          return (
            <g key={node.key}>
              <path
                d={`M ${x1} ${y1} C ${x1 + 30} ${y1}, ${x2 - 30} ${y2}, ${x2 - 6} ${y2}`}
                fill="none"
                stroke={STROKE[node.confidence]}
                strokeWidth={active ? 2.5 : 1.5}
                strokeDasharray={node.confidence === "inferred" ? "5 4" : undefined}
                markerEnd={`url(#arrow-${node.confidence})`}
                opacity={hovered && !active ? 0.35 : 1}
              />
              <g
                role={interactive ? "link" : undefined}
                tabIndex={interactive ? 0 : undefined}
                aria-label={interactive ? `Open ${node.title}` : undefined}
                onClick={node.onSelect}
                onKeyDown={(event) => {
                  if (interactive && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    node.onSelect?.();
                  }
                }}
                onMouseEnter={() => setHovered(node.key)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(node.key)}
                onBlur={() => setHovered(null)}
                className={cn(interactive && "cursor-pointer outline-none")}
              >
                <title>{node.title}</title>
                <rect
                  x={x}
                  y={y}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={6}
                  fill={active ? "#eef2ff" : "#ffffff"}
                  stroke={active ? "#4f46e5" : "#cbd5e1"}
                />
                <text x={x + 9} y={y + 17} className="fill-slate-900 font-mono text-[12px]">
                  {truncateEnd(node.label, 22)}
                </text>
                <text x={x + 9} y={y + 32} className="fill-slate-500 text-[10.5px]">
                  {truncateStart([node.relation, node.sublabel].filter(Boolean).join(" · "), 28)}
                </text>
              </g>
            </g>
          );
        })}
        {nodes.more > 0 && (
          <text
            x={x + NODE_WIDTH / 2}
            y={nodeY(nodes.shown.length, count) + NODE_HEIGHT / 2 + 4}
            textAnchor="middle"
            className="fill-slate-500 text-[11px]"
          >
            +{nodes.more} more
          </text>
        )}
      </g>
    );
  };

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="h-auto w-full min-w-[540px]" role="group" aria-label={ariaLabel}>
        <defs>
          {(["confirmed", "inferred"] as const).map((confidence) => (
            <marker
              key={confidence}
              id={`arrow-${confidence}`}
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={STROKE[confidence]} />
            </marker>
          ))}
        </defs>
        <text x={NODE_WIDTH / 2} y={14} textAnchor="middle" className="fill-slate-500 text-[11px] font-semibold uppercase">
          {incomingTitle} ({props.incoming.length})
        </text>
        <text x={RIGHT_X + NODE_WIDTH / 2} y={14} textAnchor="middle" className="fill-slate-500 text-[11px] font-semibold uppercase">
          {outgoingTitle} ({props.outgoing.length})
        </text>
        {props.incoming.length === 0 && (
          <text x={NODE_WIDTH / 2} y={centerY + NODE_HEIGHT / 2 + 4} textAnchor="middle" className="fill-slate-400 text-[11px]">
            none
          </text>
        )}
        {props.outgoing.length === 0 && (
          <text x={RIGHT_X + NODE_WIDTH / 2} y={centerY + NODE_HEIGHT / 2 + 4} textAnchor="middle" className="fill-slate-400 text-[11px]">
            none
          </text>
        )}
        {renderSide("in", incoming)}
        {renderSide("out", outgoing)}
        <g>
          <rect x={CENTER_X} y={centerY} width={NODE_WIDTH} height={NODE_HEIGHT} rx={6} fill="#4f46e5" />
          <text x={CENTER_X + 9} y={centerY + 17} className="fill-white font-mono text-[12px] font-semibold">
            {truncateEnd(center.label, 22)}
          </text>
          {center.sublabel && (
            <text x={CENTER_X + 9} y={centerY + 32} className="fill-indigo-100 text-[10.5px]">
              {truncateStart(center.sublabel, 28)}
            </text>
          )}
        </g>
      </svg>
    </div>
  );
}

export function DiagramLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-600">
      <span className="flex items-center gap-2">
        <svg width="28" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="28" y2="4" stroke={STROKE.confirmed} strokeWidth="2" />
        </svg>
        confirmed — import resolved to this file
      </span>
      <span className="flex items-center gap-2">
        <svg width="28" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="28" y2="4" stroke={STROKE.inferred} strokeWidth="2" strokeDasharray="5 4" />
        </svg>
        inferred — matched by name
      </span>
    </div>
  );
}

export function splitPath(path: string): { label: string; sublabel: string } {
  const index = path.lastIndexOf("/");
  return index === -1 ? { label: path, sublabel: "" } : { label: path.slice(index + 1), sublabel: path.slice(0, index) };
}
