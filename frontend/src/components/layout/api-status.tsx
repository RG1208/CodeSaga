"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { healthApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

type Status = "checking" | "online" | "degraded" | "offline";

const POLL_INTERVAL_MS = 30_000;

const labels: Record<Status, string> = {
  checking: "Checking API…",
  online: "API online",
  degraded: "Database unavailable",
  offline: "API offline",
};

const dotClasses: Record<Status, string> = {
  checking: "bg-slate-400",
  online: "bg-emerald-500",
  degraded: "bg-amber-500",
  offline: "bg-rose-500",
};

/** Polls the backend readiness probe and shows a status pill in the header. */
export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();

    const check = () => {
      healthApi.ready({ signal: controller.signal }).then(
        (body) => setStatus(body.status === "ok" ? "online" : "degraded"),
        (error: unknown) => {
          if (controller.signal.aborted) return;
          // The readiness endpoint answers 503 when the database is down.
          setStatus(error instanceof ApiError && error.status === 503 ? "degraded" : "offline");
        },
      );
    };

    check();
    const timer = window.setInterval(check, POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600"
      title="Backend readiness (GET /api/v1/health/ready)"
    >
      <span className={cn("size-2 rounded-full", dotClasses[status])} aria-hidden="true" />
      {labels[status]}
    </span>
  );
}
