/** Shared loading, error and empty states so every page handles them the same way. */
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { Button } from "./button";
import { AlertIcon } from "./icons";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block size-5 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600",
        className,
      )}
    />
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 px-6 py-12 text-sm text-slate-500">
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-slate-200/70", className)} />;
}

interface ErrorStateProps {
  error: Error;
  title?: string;
  onRetry?: () => void;
  retrying?: boolean;
}

export function ErrorState({
  error,
  title = "Something went wrong",
  onRetry,
  retrying = false,
}: ErrorStateProps) {
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="rounded-full bg-rose-50 p-2 text-rose-600">
        <AlertIcon />
      </span>
      <div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="mt-1 max-w-md text-sm text-slate-500">{error.message}</p>
        {requestId && (
          <p className="mt-1 font-mono text-xs text-slate-400">Request ID: {requestId}</p>
        )}
      </div>
      {onRetry && (
        <Button onClick={onRetry} disabled={retrying}>
          {retrying ? "Retrying…" : "Try again"}
        </Button>
      )}
    </div>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
}

export function EmptyState({ icon, title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      {icon && <span className="rounded-full bg-slate-100 p-2 text-slate-500">{icon}</span>}
      <div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        {description && <div className="mt-1 max-w-md text-sm text-slate-500">{description}</div>}
      </div>
    </div>
  );
}
