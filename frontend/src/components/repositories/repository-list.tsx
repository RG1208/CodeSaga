"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, buttonClassName } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { RepositoryIcon } from "@/components/ui/icons";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { repositoriesApi } from "@/lib/api/endpoints";
import { useApi } from "@/lib/hooks/use-api";
import { useInterval } from "@/lib/hooks/use-interval";
import { POLL_INTERVAL_MS, isActiveStatus } from "@/lib/repositories";

import { RepositoryTable } from "./repository-table";

const PAGE_SIZE = 20;

export function RepositoryList() {
  const [offset, setOffset] = useState(0);
  const repositories = useApi(`repositories:list:${offset}`, (signal) =>
    repositoriesApi.list({ limit: PAGE_SIZE, offset }, { signal }),
  );

  // Keep statuses live while any repository on this page is being indexed.
  const anyActive =
    repositories.status === "success" &&
    repositories.data.items.some((repository) => isActiveStatus(repository.status));
  useInterval(() => {
    if (!repositories.isRefreshing) repositories.reload();
  }, anyActive ? POLL_INTERVAL_MS : null);

  return (
    <Card>
      {repositories.status === "loading" && <LoadingState label="Loading repositories…" />}

      {repositories.status === "error" && (
        <ErrorState
          title="Could not load repositories"
          error={repositories.error}
          onRetry={repositories.reload}
          retrying={repositories.isRefreshing}
        />
      )}

      {repositories.status === "success" && repositories.data.total === 0 && (
        <div className="flex flex-col items-center pb-10">
          <EmptyState
            icon={<RepositoryIcon />}
            title="No repositories yet"
            description="Add a public GitHub repository to clone and index it."
          />
          <Link href="/repositories/new" className={buttonClassName("primary")}>
            Add repository
          </Link>
        </div>
      )}

      {repositories.status === "success" && repositories.data.total > 0 && (
        <>
          <RepositoryTable repositories={repositories.data.items} />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3 text-sm text-slate-500">
            <span>
              Showing {offset + 1}–{offset + repositories.data.items.length} of{" "}
              {repositories.data.total}
              {anyActive && " · updating live"}
            </span>
            <div className="flex gap-2">
              <Button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                disabled={offset + PAGE_SIZE >= repositories.data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
