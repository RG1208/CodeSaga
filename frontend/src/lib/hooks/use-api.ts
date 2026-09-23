"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";

import { ApiError, asApiError } from "@/lib/api/client";

interface Controls {
  /** Fetch again. Existing data stays visible while the new request runs. */
  reload: () => void;
  /** True while a reload is in flight for data that is already shown. */
  isRefreshing: boolean;
}

export type ApiState<T> = Controls &
  (
    | { status: "loading"; data: undefined; error: undefined }
    | { status: "success"; data: T; error: undefined }
    | { status: "error"; data: undefined; error: ApiError }
  );

interface Settled<T> {
  key: string;
  attempt: number;
  data?: T;
  error?: ApiError;
}

/**
 * Fetch data from the API in a Client Component, tracking loading/error state.
 *
 * `key` identifies the request: when it changes (e.g. a different page or id)
 * the data is fetched again from scratch. `reload()` refetches the same key
 * without flashing a loading state, which makes it suitable for polling.
 * In-flight requests are cancelled on unmount.
 *
 *   const repos = useApi("repositories:page-1", (signal) => repositoriesApi.list({}, { signal }));
 */
export function useApi<T>(key: string, fetcher: (signal: AbortSignal) => Promise<T>): ApiState<T> {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  const runFetch = useEffectEvent((signal: AbortSignal) => fetcher(signal));

  useEffect(() => {
    const controller = new AbortController();
    runFetch(controller.signal).then(
      (data) => setSettled({ key, attempt, data }),
      (error: unknown) => {
        if (!controller.signal.aborted) setSettled({ key, attempt, error: asApiError(error) });
      },
    );
    return () => controller.abort();
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  // Nothing yet for this key: a first load (or the key changed).
  if (settled === null || settled.key !== key) {
    return { status: "loading", data: undefined, error: undefined, reload, isRefreshing: false };
  }
  const isRefreshing = settled.attempt !== attempt;
  if (settled.error) {
    return { status: "error", data: undefined, error: settled.error, reload, isRefreshing };
  }
  return { status: "success", data: settled.data as T, error: undefined, reload, isRefreshing };
}
