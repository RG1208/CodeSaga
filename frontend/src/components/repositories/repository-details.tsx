"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { AnalysisOverview } from "@/components/code/analysis-overview";
import { Button, buttonClassName } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { BackLink } from "@/components/ui/back-link";
import {
  ExternalLinkIcon,
  RefreshIcon,
  RepositoryIcon,
  TrashIcon,
} from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { ApiError, asApiError } from "@/lib/api/client";
import { repositoriesApi } from "@/lib/api/endpoints";
import type {
  RepositoryDetail,
  RepositoryMetadata,
  RetrievalSummary,
} from "@/lib/api/types";
import { useApi } from "@/lib/hooks/use-api";
import { useInterval } from "@/lib/hooks/use-interval";
import {
  POLL_INTERVAL_MS,
  codeExplorerUrl,
  commitUrl,
  isActiveStatus,
  repositoryFullName,
  shortSha,
} from "@/lib/repositories";
import {
  cn,
  formatBytes,
  formatDateTime,
  formatNumber,
  formatRelativeTime,
} from "@/lib/utils";

import { IndexingProgress } from "./indexing-progress";
import { LanguageBreakdown } from "./language-breakdown";
import {
  RepositorySourceBadge,
  RepositoryStatusBadge,
} from "./repository-status-badge";

const CHUNK_TYPE_HINTS: Record<string, string> = {
  symbol: "A whole function, class or method",
  symbol_header:
    "A class signature and docstring, when its members are chunked separately",
  symbol_part: "One window of a symbol too large for a single chunk",
  module: "Module-level code outside any symbol",
  section: "A documentation section",
  window: "A block of a file with no structure to follow",
};

function MetadataRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-5 gap-3 px-5 py-2.5 text-sm">
      <dt className="col-span-2 text-slate-500">{label}</dt>
      <dd className="col-span-3 min-w-0 break-words text-slate-900">
        {children}
      </dd>
    </div>
  );
}

function StatTile({
  label,
  value,
  title,
  small,
}: {
  label: string;
  value: ReactNode;
  title?: string;
  small?: boolean;
}) {
  return (
    <div className="rounded-lg bg-slate-50 px-4 py-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p
        title={title}
        className={cn(
          "mt-1 truncate font-semibold text-slate-900",
          small ? "text-sm" : "text-lg",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function RepositoryInsights({ metadata }: { metadata: RepositoryMetadata }) {
  const skipped = Object.values(metadata.skipped_files).reduce(
    (sum, count) => sum + count,
    0,
  );
  return (
    <div className="space-y-6 px-5 py-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Files" value={formatNumber(metadata.total_files)} />
        <StatTile
          label="Indexed files"
          value={formatNumber(metadata.indexed_files)}
        />
        <StatTile label="Size" value={formatBytes(metadata.total_size_bytes)} />
        <StatTile
          label="Primary language"
          value={metadata.primary_language ?? "—"}
        />
      </div>
      {skipped > 0 && (
        <p className="-mt-3 text-xs text-slate-500">
          {formatNumber(skipped)} files not indexed (binary, too large, or not
          regular files).
        </p>
      )}

      <section>
        <h3 className="text-sm font-semibold text-slate-900">Languages</h3>
        <p className="text-xs text-slate-500">
          Share of bytes in recognized files
        </p>
        <div className="mt-2">
          <LanguageBreakdown languages={metadata.languages} />
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-slate-900">Project files</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {[metadata.readme_path, metadata.license_path, ...metadata.manifests]
            .filter((path): path is string => Boolean(path))
            .map((path) => (
              <span
                key={path}
                className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700"
              >
                {path}
              </span>
            ))}
          {!metadata.readme_path &&
            !metadata.license_path &&
            metadata.manifests.length === 0 && (
              <span className="text-sm text-slate-500">
                No README, license or manifest found.
              </span>
            )}
        </div>
      </section>
    </div>
  );
}

function SearchIndexSummary({ retrieval }: { retrieval: RetrievalSummary }) {
  const dense = retrieval.dense;
  const denseValue =
    dense.status === "ready"
      ? `${formatNumber(dense.vectors ?? 0)} vectors`
      : dense.status;
  const chunkTypes = Object.entries(retrieval.chunk_types).sort(
    (a, b) => b[1] - a[1],
  );
  return (
    <div className="space-y-5 px-5 py-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Chunks" value={formatNumber(retrieval.chunks)} />
        <StatTile
          label="BM25 terms"
          value={formatNumber(retrieval.bm25.terms)}
        />
        <StatTile label="Dense vectors" value={denseValue} />
        <StatTile
          label="Embedding model"
          // Model ids are "org/name"; the name is the part that distinguishes them.
          value={dense.model?.split("/").at(-1) ?? "—"}
          title={dense.model ?? undefined}
          small
        />
      </div>

      {dense.status !== "ready" && (
        <p className="-mt-3 text-xs text-slate-500">
          {dense.status === "disabled"
            ? "Dense retrieval is switched off (DENSE_RETRIEVAL_ENABLED=false); lexical BM25 search still works."
            : `Dense index unavailable: ${dense.reason ?? dense.status}. Lexical BM25 search still works.`}
        </p>
      )}

      <section>
        <h3 className="text-sm font-semibold text-slate-900">Chunk types</h3>
        <p className="text-xs text-slate-500">
          Code is split along symbol boundaries, not at a fixed character count.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {chunkTypes.map(([type, count]) => (
            <span
              key={type}
              className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700"
              title={CHUNK_TYPE_HINTS[type] ?? type}
            >
              {type.replace(/_/g, " ")} · {formatNumber(count)}
            </span>
          ))}
        </div>
      </section>

      <p className="text-xs text-slate-500">
        Search this repository with{" "}
        <code className="font-mono whitespace-nowrap">
          POST /api/v1/repositories/{"{id}"}/search
        </code>{" "}
        using strategy <span className="font-mono">bm25</span>,{" "}
        <span className="font-mono">dense</span>,{" "}
        <span className="font-mono">hybrid</span> or{" "}
        <span className="font-mono whitespace-nowrap">hybrid_rerank</span>. The
        chat interface arrives in a later phase.
      </p>
    </div>
  );
}

function RepositoryFacts({ repository }: { repository: RepositoryDetail }) {
  const lastCommit = repository.metadata?.last_commit;
  const commitLink = repository.commit_sha
    ? commitUrl(repository, repository.commit_sha)
    : null;
  return (
    <dl className="divide-y divide-slate-100 py-1">
      <MetadataRow label="Source">
        <RepositorySourceBadge source={repository.source_type} />
      </MetadataRow>
      <MetadataRow label={repository.source_type === "github" ? "URL" : "Path"}>
        {repository.source_type === "github" ? (
          <a
            href={repository.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-indigo-600 hover:underline"
          >
            {repository.url.replace("https://", "")}
            <ExternalLinkIcon className="size-3.5" />
          </a>
        ) : (
          <span className="font-mono text-xs">{repository.url}</span>
        )}
      </MetadataRow>
      {repository.owner && (
        <MetadataRow label="Owner">{repository.owner}</MetadataRow>
      )}
      <MetadataRow label="Branch">
        <span className="font-mono text-xs">{repository.branch}</span>
        {repository.branch !== repository.default_branch && (
          <span className="block text-xs text-slate-500">
            default:{" "}
            <span className="font-mono">{repository.default_branch}</span>
          </span>
        )}
      </MetadataRow>
      <MetadataRow label="Indexed commit">
        {repository.commit_sha ? (
          commitLink ? (
            <a
              href={commitLink}
              target="_blank"
              rel="noreferrer"
              className="font-mono text-xs text-indigo-600 hover:underline"
              title={repository.commit_sha}
            >
              {shortSha(repository.commit_sha)}
            </a>
          ) : (
            <span className="font-mono text-xs" title={repository.commit_sha}>
              {shortSha(repository.commit_sha)}
            </span>
          )
        ) : (
          <span className="text-slate-500">Not indexed yet</span>
        )}
      </MetadataRow>
      {lastCommit && (
        <MetadataRow label="Last commit">
          <span className="block">{lastCommit.subject}</span>
          <span className="block text-xs text-slate-500">
            {lastCommit.author_name} ·{" "}
            {formatRelativeTime(lastCommit.authored_at)}
          </span>
        </MetadataRow>
      )}
      <MetadataRow label="Last indexed">
        {repository.last_indexed_at
          ? formatDateTime(repository.last_indexed_at)
          : "Never"}
      </MetadataRow>
      {repository.local_path && (
        <MetadataRow label="Local checkout">
          <span className="font-mono text-xs">{repository.local_path}</span>
        </MetadataRow>
      )}
      <MetadataRow label="Added">
        {formatDateTime(repository.created_at)}
      </MetadataRow>
    </dl>
  );
}

function RepositoryView({
  repository,
  onChanged,
}: {
  repository: RepositoryDetail;
  onChanged: () => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<"index" | "delete" | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const active = isActiveStatus(repository.status);
  const neverIndexed =
    repository.status === "pending" && repository.latest_job === null;

  async function handleIndex() {
    setBusy("index");
    setActionError(null);
    try {
      await repositoriesApi.startIndexing(repository.id);
      onChanged();
    } catch (error) {
      setActionError(asApiError(error));
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    const confirmed = window.confirm(
      `Delete ${repositoryFullName(repository)}?\n\nThis removes the repository, its index and its local checkout.`,
    );
    if (!confirmed) return;
    setBusy("delete");
    setActionError(null);
    try {
      await repositoriesApi.remove(repository.id);
      router.push("/repositories");
    } catch (error) {
      setActionError(asApiError(error));
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title={repositoryFullName(repository)}
        description={
          repository.source_type === "github"
            ? "GitHub repository"
            : "Local repository"
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <RepositoryStatusBadge status={repository.status} />
            {repository.local_path && (
              <Link
                href={codeExplorerUrl(repository.id)}
                className={buttonClassName("secondary")}
              >
                Browse code
              </Link>
            )}
            <Button
              variant="primary"
              onClick={handleIndex}
              disabled={active || busy !== null}
            >
              <RefreshIcon
                className={busy === "index" ? "size-4 animate-spin" : "size-4"}
              />
              {neverIndexed ? "Start indexing" : "Re-index"}
            </Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={active || busy !== null}
              title={
                active
                  ? "Wait for indexing to finish before deleting"
                  : undefined
              }
            >
              <TrashIcon className="size-4" />
              {busy === "delete" ? "Deleting…" : "Delete"}
            </Button>
          </div>
        }
      />

      {actionError && (
        <div
          role="alert"
          className="mb-6 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800"
        >
          {actionError.message}
        </div>
      )}

      <Card className="mb-6">
        <CardHeader
          title="Indexing"
          description={
            neverIndexed
              ? "Clone the repository, analyze it and build its file index."
              : "Clone → analyze → index → parse → search index. Updates automatically while running."
          }
        />
        {neverIndexed ? (
          <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-5">
            <p className="text-sm text-slate-600">
              This repository has not been indexed yet. Indexing runs in the
              background; you can leave this page.
            </p>
            <Button
              variant="primary"
              onClick={handleIndex}
              disabled={busy !== null}
            >
              Start indexing
            </Button>
          </div>
        ) : (
          <IndexingProgress repository={repository} />
        )}
      </Card>

      {repository.local_path && (
        <Card className="mb-6">
          <CardHeader
            title="Code structure"
            description="Symbols, imports and dependencies extracted with Tree-sitter."
            action={
              repository.metadata?.analysis ? (
                <Link
                  href={codeExplorerUrl(repository.id)}
                  className="text-sm font-medium whitespace-nowrap text-indigo-600 hover:text-indigo-500"
                >
                  Open explorer
                </Link>
              ) : undefined
            }
          />
          {repository.metadata?.analysis ? (
            <div className="px-5 py-5">
              <AnalysisOverview
                summary={repository.metadata.analysis}
                onOpenFile={(path) =>
                  router.push(codeExplorerUrl(repository.id, path))
                }
              />
            </div>
          ) : (
            <p className="px-5 py-5 text-sm text-slate-600">
              This repository was indexed before code analysis was available.
              Re-index it to extract functions, classes, imports and the
              dependency graph.
            </p>
          )}
        </Card>
      )}

      {repository.metadata?.retrieval && (
        <Card className="mb-6">
          <CardHeader
            title="Search index"
            description="Code-aware chunks, a BM25 lexical index and dense embeddings."
          />
          <SearchIndexSummary retrieval={repository.metadata.retrieval} />
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader
            title="Overview"
            description="Extracted from the indexed commit."
          />
          {repository.metadata ? (
            <RepositoryInsights metadata={repository.metadata} />
          ) : (
            <EmptyState
              icon={<RepositoryIcon />}
              title="No analysis yet"
              description="Languages, file counts and project files appear after indexing completes."
            />
          )}
        </Card>

        <Card className="self-start lg:col-span-2">
          <CardHeader title="Details" />
          <RepositoryFacts repository={repository} />
        </Card>
      </div>
    </>
  );
}

export function RepositoryDetails({ repositoryId }: { repositoryId: string }) {
  const repository = useApi(`repositories:get:${repositoryId}`, (signal) =>
    repositoriesApi.get(repositoryId, { signal }),
  );

  const active =
    repository.status === "success" && isActiveStatus(repository.data.status);
  useInterval(
    () => {
      if (!repository.isRefreshing) repository.reload();
    },
    active ? POLL_INTERVAL_MS : null,
  );

  return (
    <div>
      <BackLink href="/repositories" label="All repositories" />

      {repository.status === "loading" && (
        <Card>
          <LoadingState label="Loading repository…" />
        </Card>
      )}

      {repository.status === "error" &&
        (repository.error.isNotFound || repository.error.status === 422 ? (
          <Card>
            <EmptyState
              icon={<RepositoryIcon />}
              title="Repository not found"
              description="It may have been deleted, or the link is incorrect."
            />
          </Card>
        ) : (
          <Card>
            <ErrorState
              title="Could not load repository"
              error={repository.error}
              onRetry={repository.reload}
              retrying={repository.isRefreshing}
            />
          </Card>
        ))}

      {repository.status === "success" && (
        <RepositoryView
          repository={repository.data}
          onChanged={repository.reload}
        />
      )}
    </div>
  );
}
