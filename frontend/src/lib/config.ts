/**
 * Runtime configuration for the browser.
 *
 * `NEXT_PUBLIC_*` variables are inlined into the JavaScript bundle when the
 * dev server starts or `next build` runs, so changing them requires a restart.
 */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"
).replace(/\/+$/, "");
