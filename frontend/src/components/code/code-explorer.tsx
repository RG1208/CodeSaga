"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { BackLink } from "@/components/ui/back-link";
import { buttonClassName } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { codeApi, repositoriesApi } from "@/lib/api/endpoints";
import type { CodeFileDetail, CodeSymbol, Relationship, RepositoryDetail } from "@/lib/api/types";
import { useApi } from "@/lib/hooks/use-api";
import { codeExplorerUrl, repositoryFullName } from "@/lib/repositories";
import { cn } from "@/lib/utils";

import { AnalysisOverview } from "./analysis-overview";
import { type DiagramNode, DependencyDiagram, DiagramLegend, splitPath } from "./dependency-diagram";
import { FileTree } from "./file-tree";
import { ModulePanel } from "./module-panel";
import { SourceViewer } from "./source-viewer";
import { SymbolDetails } from "./symbol-details";
import { SymbolOutline } from "./symbol-outline";
import { SymbolSearch } from "./symbol-search";

type CenterView = "source" | "dependencies";
type InspectorTab = "symbols" | "module";

export function CodeExplorer({ repositoryId }: { repositoryId: string }) {
  const repository = useApi(`repositories:get:${repositoryId}`, (signal) =>
    repositoriesApi.get(repositoryId, { signal }),
  );

  if (repository.status === "loading") return <LoadingState label="Loading repository…" />;
  if (repository.status === "error") {
    return (
      <Card>
        <ErrorState title="Could not load repository" error={repository.error} onRetry={repository.reload} />
      </Card>
    );
  }
  return <Explorer repository={repository.data} />;
}

function Explorer({ repository }: { repository: RepositoryDetail }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const path = searchParams.get("path");
  const symbolId = searchParams.get("symbol");
  const [view, setView] = useState<CenterView>("source");
  const [tab, setTab] = useState<InspectorTab>("symbols");
  const repositoryId = repository.id;

  const files = useApi(`code:files:${repositoryId}`, (signal) =>
    codeApi.files(repositoryId, { limit: 20000 }, { signal }),
  );
  const selectedFile =
    files.status === "success" && path ? (files.data.items.find((file) => file.path === path) ?? null) : null;
  const detail = useApi(`code:detail:${repositoryId}:${selectedFile?.analyzed ? path : ""}`, (signal) =>
    selectedFile?.analyzed && path ? codeApi.fileDetail(repositoryId, path, { signal }) : Promise.resolve(null),
  );
  const fileDetail: CodeFileDetail | null = detail.status === "success" ? detail.data : null;
  const selectedSymbol = fileDetail?.symbols.find((symbol) => symbol.id === symbolId) ?? null;
  const symbolEdges = useApi(`code:symbol-edges:${repositoryId}:${selectedSymbol?.id ?? ""}`, (signal) =>
    selectedSymbol
      ? codeApi.dependencies(repositoryId, { symbolId: selectedSymbol.id, limit: 100 }, { signal })
      : Promise.resolve(null),
  );

  const openFile = (nextPath: string, nextSymbolId: string | null = null) =>
    router.push(codeExplorerUrl(repositoryId, nextPath, nextSymbolId), { scroll: false });
  const selectSymbol = (symbol: CodeSymbol) => {
    setView("source");
    router.replace(codeExplorerUrl(repositoryId, path, symbol.id === symbolId ? null : symbol.id), { scroll: false });
  };

  const summary = repository.metadata?.analysis ?? null;
  const notIndexed = repository.local_path === null;

  return (
    <div>
      <BackLink href={`/repositories/${repositoryId}`} label="Repository details" />
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-900">
            {repositoryFullName(repository)}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Source code explorer · branch <span className="font-mono">{repository.branch}</span>
            {repository.commit_sha && (
              <>
                {" "}
                · commit <span className="font-mono">{repository.commit_sha.slice(0, 7)}</span>
              </>
            )}
          </p>
        </div>
        {summary && (
          <SymbolSearch repositoryId={repositoryId} onSelect={(symbol) => openFile(symbol.file_path, symbol.id)} />
        )}
      </div>

      {notIndexed ? (
        <Card>
          <EmptyState
            title="This repository has not been indexed yet"
            description="Start indexing from the repository page to browse its code."
          />
          <div className="flex justify-center pb-8">
            <Link href={`/repositories/${repositoryId}`} className={buttonClassName("primary")}>
              Go to repository
            </Link>
          </div>
        </Card>
      ) : (
        <>
          {!summary && (
            <div className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
              This repository was indexed before code analysis was available. Files can be browsed, but symbols and
              dependencies appear after you <strong>re-index</strong> it.
            </div>
          )}
          <div className="grid gap-4 xl:h-[calc(100vh-15rem)] xl:min-h-[34rem] xl:grid-cols-[17rem_minmax(0,1fr)_23rem]">
            <Card className="flex max-h-[28rem] min-h-0 flex-col overflow-hidden xl:max-h-none">
              {files.status === "loading" && <LoadingState label="Loading files…" />}
              {files.status === "error" && (
                <ErrorState title="Could not load files" error={files.error} onRetry={files.reload} />
              )}
              {files.status === "success" && (
                <FileTree files={files.data.items} selectedPath={path} onSelect={(next) => openFile(next)} />
              )}
            </Card>

            <Card className="flex h-[36rem] min-h-0 flex-col overflow-hidden xl:h-auto">
              {!path ? (
                <div className="overflow-y-auto p-5">
                  {summary ? (
                    <>
                      <h2 className="mb-4 text-sm font-semibold text-slate-900">Code structure</h2>
                      <AnalysisOverview summary={summary} onOpenFile={(next) => openFile(next)} />
                    </>
                  ) : (
                    <EmptyState title="Select a file" description="Choose a file in the tree to view its source." />
                  )}
                </div>
              ) : (
                <>
                  <ViewToggle view={view} onChange={setView} dependenciesEnabled={Boolean(fileDetail)} />
                  <div className="min-h-0 flex-1">
                    {view === "source" || !fileDetail ? (
                      <SourceViewer
                        key={path}
                        repositoryId={repositoryId}
                        path={path}
                        highlight={
                          selectedSymbol ? { start: selectedSymbol.start_line, end: selectedSymbol.end_line } : null
                        }
                      />
                    ) : (
                      <DependenciesView
                        detail={fileDetail}
                        symbol={selectedSymbol}
                        symbolEdges={symbolEdges.status === "success" ? symbolEdges.data?.items ?? [] : []}
                        onOpen={openFile}
                      />
                    )}
                  </div>
                </>
              )}
            </Card>

            <Card className="flex min-h-0 flex-col overflow-hidden">
              {!path && (
                <p className="px-4 py-6 text-sm text-slate-500">
                  Select a file to see its symbols, imports and dependencies, or search for a symbol above.
                </p>
              )}
              {path && selectedFile && !selectedFile.analyzed && (
                <p className="px-4 py-6 text-sm text-slate-500">
                  This file was not parsed: only Python, JavaScript, TypeScript and TSX source files are analyzed
                  (very large or generated files are skipped).
                </p>
              )}
              {path && files.status === "success" && !selectedFile && (
                <p className="px-4 py-6 text-sm text-slate-500">This file is not in the repository index.</p>
              )}
              {selectedFile?.analyzed && detail.status === "loading" && <LoadingState label="Analyzing file…" />}
              {selectedFile?.analyzed && detail.status === "error" && (
                <ErrorState title="Could not load file analysis" error={detail.error} onRetry={detail.reload} />
              )}
              {fileDetail && (
                <>
                  <div className="flex border-b border-slate-100 text-sm" role="tablist">
                    {(
                      [
                        ["symbols", `Symbols (${fileDetail.symbol_count})`],
                        ["module", "Imports & exports"],
                      ] as const
                    ).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        role="tab"
                        aria-selected={tab === value}
                        onClick={() => setTab(value)}
                        className={cn(
                          "flex-1 border-b-2 px-3 py-2.5 font-medium whitespace-nowrap",
                          tab === value
                            ? "border-indigo-600 text-indigo-700"
                            : "border-transparent text-slate-500 hover:text-slate-800",
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    {fileDetail.parse_status !== "parsed" && (
                      <p className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-900">
                        {fileDetail.parse_status === "failed"
                          ? "The parser could not process this file."
                          : `Parsed partially: ${fileDetail.metadata.syntax_errors ?? "some"} region(s) could not be parsed (a syntax error, or syntax the grammar does not support). Other results are complete.`}
                      </p>
                    )}
                    {tab === "symbols" ? (
                      <>
                        {selectedSymbol && (
                          <SymbolDetails symbol={selectedSymbol} edges={symbolEdges} onNavigate={openFile} />
                        )}
                        <SymbolOutline
                          symbols={fileDetail.symbols}
                          selectedId={selectedSymbol?.id ?? null}
                          onSelect={selectSymbol}
                        />
                      </>
                    ) : (
                      <ModulePanel detail={fileDetail} onOpenFile={(next) => openFile(next)} />
                    )}
                  </div>
                </>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function ViewToggle({
  view,
  onChange,
  dependenciesEnabled,
}: {
  view: CenterView;
  onChange: (view: CenterView) => void;
  dependenciesEnabled: boolean;
}) {
  return (
    <div className="flex gap-1 border-b border-slate-100 px-3 py-2" role="tablist" aria-label="View">
      {(
        [
          ["source", "Source"],
          ["dependencies", "Dependencies"],
        ] as const
      ).map(([value, label]) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={view === value}
          disabled={value === "dependencies" && !dependenciesEnabled}
          onClick={() => onChange(value)}
          className={cn(
            "rounded-md px-2.5 py-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40",
            view === value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function DependenciesView({
  detail,
  symbol,
  symbolEdges,
  onOpen,
}: {
  detail: CodeFileDetail;
  symbol: CodeSymbol | null;
  symbolEdges: Relationship[];
  onOpen: (path: string, symbolId?: string | null) => void;
}) {
  const fileNode = (dependency: CodeFileDetail["depends_on"][number]): DiagramNode => ({
    key: dependency.relationship_id,
    ...splitPath(dependency.path),
    title: `${dependency.path}\n${dependency.confidence} · ${dependency.specifiers.join(", ")}`,
    confidence: dependency.confidence,
    onSelect: () => onOpen(dependency.path),
  });
  const symbolNode = (side: "source" | "target") => (edge: (typeof symbolEdges)[number]): DiagramNode => {
    const other = side === "target" ? edge.target_symbol : edge.source_symbol;
    const otherPath = side === "target" ? edge.target_path : edge.source_path;
    return {
      key: edge.id,
      label: other?.qualified_name ?? "?",
      sublabel: otherPath,
      relation: edge.relationship_type,
      title: `${other?.qualified_name} — ${otherPath}\n${edge.relationship_type} · ${edge.confidence} (resolved via ${edge.metadata.resolution})`,
      confidence: edge.confidence,
      onSelect: () => onOpen(otherPath, other?.id ?? null),
    };
  };

  return (
    <div className="h-full space-y-6 overflow-y-auto p-5">
      <DiagramLegend />
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">File imports</h3>
        <DependencyDiagram
          center={splitPath(detail.path)}
          incoming={detail.imported_by.map(fileNode)}
          outgoing={detail.depends_on.map(fileNode)}
          incomingTitle="Imported by"
          outgoingTitle="Imports"
          ariaLabel={`Files importing and imported by ${detail.path}`}
        />
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          {symbol ? (
            <>
              Symbol relationships · <span className="font-mono">{symbol.qualified_name}</span>
            </>
          ) : (
            "Symbol relationships"
          )}
        </h3>
        {symbol ? (
          <DependencyDiagram
            center={{ label: symbol.qualified_name, sublabel: detail.path }}
            incoming={symbolEdges.filter((edge) => edge.target_symbol?.id === symbol.id).map(symbolNode("source"))}
            outgoing={symbolEdges.filter((edge) => edge.source_symbol?.id === symbol.id).map(symbolNode("target"))}
            incomingTitle="Used by"
            outgoingTitle="Uses"
            ariaLabel={`Calls and renders involving ${symbol.qualified_name}`}
          />
        ) : (
          <p className="text-sm text-slate-500">
            Select a symbol in the Symbols list to see what calls it and what it calls.
          </p>
        )}
      </section>
    </div>
  );
}
