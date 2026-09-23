"use client";

import Link from "next/link";

import { Card, CardHeader } from "@/components/ui/card";
import { CheckIcon, ProjectIcon, RepositoryIcon } from "@/components/ui/icons";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { projectsApi, repositoriesApi } from "@/lib/api/endpoints";
import { useApi } from "@/lib/hooks/use-api";
import { repositoryFullName } from "@/lib/repositories";
import { formatDate } from "@/lib/utils";

import { RepositoryStatusBadge } from "../repositories/repository-status-badge";
import { StatCard } from "./stat-card";

const RECENT_LIMIT = 5;

export function DashboardOverview() {
  // `limit: 1` is enough to read the total count from the page metadata.
  const projects = useApi("dashboard:projects", (signal) =>
    projectsApi.list({ limit: 1 }, { signal }),
  );
  const repositories = useApi("dashboard:repositories", (signal) =>
    repositoriesApi.list({ limit: RECENT_LIMIT }, { signal }),
  );
  const indexed = useApi("dashboard:indexed", (signal) =>
    repositoriesApi.list({ status: "completed", limit: 1 }, { signal }),
  );

  const errorValue = <span className="text-base font-medium text-rose-600">Unavailable</span>;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Projects"
          icon={ProjectIcon}
          value={projects.status === "error" ? errorValue : projects.data?.total}
          hint="Workspaces grouping repositories"
        />
        <StatCard
          label="Repositories"
          icon={RepositoryIcon}
          value={repositories.status === "error" ? errorValue : repositories.data?.total}
          hint="Registered for analysis"
        />
        <StatCard
          label="Indexed"
          icon={CheckIcon}
          value={indexed.status === "error" ? errorValue : indexed.data?.total}
          hint="Cloned, analyzed and indexed"
        />
      </div>

      <Card>
        <CardHeader
          title="Recent repositories"
          description="The latest repositories registered in CodeSage."
          action={
            <div className="flex items-center gap-4">
              <Link
                href="/repositories/new"
                className="text-sm font-medium whitespace-nowrap text-indigo-600 hover:text-indigo-500"
              >
                Add repository
              </Link>
              <Link
                href="/repositories"
                className="text-sm font-medium whitespace-nowrap text-slate-600 hover:text-slate-900"
              >
                View all
              </Link>
            </div>
          }
        />

        {repositories.status === "loading" && <LoadingState label="Loading repositories…" />}

        {repositories.status === "error" && (
          <ErrorState
            title="Could not load repositories"
            error={repositories.error}
            onRetry={repositories.reload}
          />
        )}

        {repositories.status === "success" && repositories.data.items.length === 0 && (
          <EmptyState
            icon={<RepositoryIcon />}
            title="No repositories yet"
            description="Add a GitHub repository to see it here."
          />
        )}

        {repositories.status === "success" && repositories.data.items.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {repositories.data.items.map((repository) => (
              <li key={repository.id}>
                <Link
                  href={`/repositories/${repository.id}`}
                  className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-900">
                      {repositoryFullName(repository)}
                    </p>
                    <p className="truncate text-xs text-slate-500">{repository.url}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className="hidden text-xs text-slate-400 sm:inline">
                      {formatDate(repository.created_at)}
                    </span>
                    <RepositoryStatusBadge status={repository.status} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
