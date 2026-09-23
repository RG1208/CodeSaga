import { CheckIcon, CloseIcon } from "@/components/ui/icons";
import type {
  IndexingJob,
  RepositoryDetail,
  RepositoryStatus,
} from "@/lib/api/types";
import { shortSha } from "@/lib/repositories";
import {
  cn,
  formatDuration,
  formatNumber,
  formatRelativeTime,
} from "@/lib/utils";

type StepState = "done" | "current" | "failed" | "upcoming";

const PROGRESS_LABELS: Partial<Record<RepositoryStatus, string>> = {
  indexing: "Files indexed",
  parsing: "Files parsed",
  embedding: "Chunks embedded",
};

const STEPS: { stage: RepositoryStatus; label: string; description: string }[] =
  [
    { stage: "cloning", label: "Clone", description: "Fetching the branch" },
    {
      stage: "analyzing",
      label: "Analyze",
      description: "Detecting languages",
    },
    { stage: "indexing", label: "Index", description: "Reading every file" },
    { stage: "parsing", label: "Parse", description: "Symbols & dependencies" },
    { stage: "embedding", label: "Search", description: "Chunks & embeddings" },
    { stage: "completed", label: "Done", description: "Index ready" },
  ];

function stepStates(repository: RepositoryDetail): StepState[] {
  const { status, latest_job: job } = repository;
  if (status === "completed") return STEPS.map(() => "done");
  if (status === "queued" || status === "pending")
    return STEPS.map(() => "upcoming");

  const reached = status === "failed" ? (job?.stage ?? "cloning") : status;
  const reachedIndex = Math.max(
    0,
    STEPS.findIndex((step) => step.stage === reached),
  );
  return STEPS.map((_, index) => {
    if (index < reachedIndex) return "done";
    if (index > reachedIndex) return "upcoming";
    return status === "failed" ? "failed" : "current";
  });
}

function StepMarker({
  state,
  position,
}: {
  state: StepState;
  position: number;
}) {
  const base =
    "grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold";
  if (state === "done") {
    return (
      <span className={cn(base, "bg-indigo-600 text-white")}>
        <CheckIcon className="size-4" />
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span className={cn(base, "bg-rose-600 text-white")}>
        <CloseIcon className="size-4" />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span
        className={cn(
          base,
          "border-2 border-indigo-600 bg-white text-indigo-600",
        )}
      >
        <span className="size-3 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
      </span>
    );
  }
  return (
    <span
      className={cn(base, "border-2 border-slate-200 bg-white text-slate-400")}
    >
      {position}
    </span>
  );
}

function ProgressBar({
  job,
  status,
}: {
  job: IndexingJob | null;
  status: RepositoryStatus;
}) {
  const counted =
    status === "indexing" || status === "parsing" || status === "embedding";
  if (counted && job?.files_total) {
    const percent = Math.min(
      100,
      Math.round((job.files_processed / job.files_total) * 100),
    );
    return (
      <div>
        <div
          role="progressbar"
          aria-label={PROGRESS_LABELS[status] ?? "Progress"}
          aria-valuemin={0}
          aria-valuemax={job.files_total}
          aria-valuenow={job.files_processed}
          className="h-2 overflow-hidden rounded-full bg-slate-100"
        >
          <div
            className="h-full rounded-full bg-indigo-600 transition-[width] duration-500"
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs text-slate-500">
          {formatNumber(job.files_processed)} of {formatNumber(job.files_total)}{" "}
          {status === "embedding" ? "chunks" : "files"} · {percent}%
        </p>
      </div>
    );
  }
  return (
    // Indeterminate: git reports no usable progress, so a sliding bar shows activity only.
    <div
      role="progressbar"
      aria-label="Working"
      aria-valuetext="In progress"
      className="relative h-2 overflow-hidden rounded-full bg-slate-100"
    >
      <div className="animate-indeterminate absolute inset-y-0 w-1/3 rounded-full bg-indigo-500" />
    </div>
  );
}

export function IndexingProgress({
  repository,
}: {
  repository: RepositoryDetail;
}) {
  const { status, latest_job: job } = repository;
  const states = stepStates(repository);
  const active = status === "queued" || states.includes("current");

  let summary: string;
  if (status === "queued") summary = "Waiting for a background worker…";
  else if (active) {
    const step = STEPS[states.indexOf("current")];
    summary = `${step.label}: ${step.description.toLowerCase()}…`;
  } else if (status === "completed" && job?.started_at && job.finished_at) {
    summary = `Indexed commit ${shortSha(repository.commit_sha)} in ${formatDuration(job.started_at, job.finished_at)}.`;
  } else if (status === "failed") {
    summary = "Indexing failed.";
  } else {
    summary = "Indexed.";
  }

  return (
    <div className="space-y-5 px-5 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slate-900" aria-live="polite">
          {summary}
        </p>
        {job?.started_at && (
          <p className="text-xs text-slate-500">
            {job.finished_at
              ? `Finished ${formatRelativeTime(job.finished_at)}`
              : `Started ${formatRelativeTime(job.started_at)}`}
            {" · "}branch <span className="font-mono">{job.branch}</span>
          </p>
        )}
      </div>

      <ol className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {STEPS.map((step, index) => (
          <li
            key={step.stage}
            aria-current={states[index] === "current" ? "step" : undefined}
            className="flex items-center gap-3"
          >
            <StepMarker state={states[index]} position={index + 1} />
            <div className="min-w-0">
              <p
                className={cn(
                  "text-sm font-medium",
                  states[index] === "upcoming"
                    ? "text-slate-400"
                    : "text-slate-900",
                )}
              >
                {step.label}
              </p>
              <p className="truncate text-xs text-slate-500">
                {step.description}
              </p>
            </div>
          </li>
        ))}
      </ol>

      {active && <ProgressBar job={job} status={status} />}

      {status === "failed" && (
        <div
          role="alert"
          className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800"
        >
          {repository.status_message ??
            job?.error_message ??
            "Indexing failed."}
          {repository.commit_sha && (
            <p className="mt-1 text-rose-700">
              The previous index (commit {shortSha(repository.commit_sha)}) is
              still available.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
