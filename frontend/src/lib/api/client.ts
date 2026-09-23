/**
 * Thin, typed wrapper around `fetch` for the CodeSage API.
 *
 * Every failure — HTTP error, timeout or unreachable server — is normalised
 * into an `ApiError`, so UI code only has to handle one error type.
 */
import { API_BASE_URL } from "@/lib/config";

import type { ApiErrorBody } from "./types";

const DEFAULT_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  constructor(
    message: string,
    /** HTTP status code, or 0 when no response was received. */
    readonly status: number,
    readonly code: string,
    readonly details: unknown = null,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Record<string, QueryValue>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(`${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  try {
    const { error } = (await response.json()) as ApiErrorBody;
    return new ApiError(error.message, response.status, error.code, error.details, requestId);
  } catch {
    return new ApiError(
      `Request failed with status ${response.status}.`,
      response.status,
      "http_error",
      null,
      requestId,
    );
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, headers, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const combinedSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined && { "Content-Type": "application/json" }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: combinedSignal,
    });
  } catch (error) {
    // The caller cancelled (e.g. component unmounted): let them ignore it.
    if (signal?.aborted) throw error;
    if (timeoutSignal.aborted) {
      throw new ApiError("The CodeSage API did not respond in time.", 0, "timeout");
    }
    throw new ApiError(`Cannot reach the CodeSage API at ${API_BASE_URL}.`, 0, "network_error");
  }

  if (!response.ok) throw await errorFromResponse(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Coerce anything thrown into an ApiError. */
export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : "Unexpected error.";
  return new ApiError(message, 0, "unknown_error");
}
