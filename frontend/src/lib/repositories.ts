import type { Repository, RepositoryStatus } from "@/lib/api/types";

/** Statuses during which the backend is working and the UI should poll. */
export const ACTIVE_STATUSES: ReadonlySet<RepositoryStatus> = new Set([
  "queued",
  "cloning",
  "analyzing",
  "indexing",
  "parsing",
  "embedding",
]);

export const POLL_INTERVAL_MS = 2000;

export function isActiveStatus(status: RepositoryStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function shortSha(sha: string | null): string {
  return sha ? sha.slice(0, 7) : "—";
}

/** "owner/name" for GitHub repositories, the plain name otherwise. */
export function repositoryFullName(
  repository: Pick<Repository, "owner" | "name">,
): string {
  return repository.owner
    ? `${repository.owner}/${repository.name}`
    : repository.name;
}

export function commitUrl(repository: Repository, sha: string): string | null {
  return repository.source_type === "github"
    ? `${repository.url}/commit/${sha}`
    : null;
}

const GITHUB_URL_PATTERN =
  /^https:\/\/(www\.)?github\.com\/[^/\s]+\/[^/\s]+?(\.git)?\/?$/i;

/** Quick client-side check for instant feedback; the backend does the real validation. */
export function looksLikeGitHubUrl(value: string): boolean {
  return GITHUB_URL_PATTERN.test(value.trim());
}

/** URL of the code explorer, optionally opened at a file and symbol. */
export function codeExplorerUrl(
  repositoryId: string,
  path?: string | null,
  symbolId?: string | null,
): string {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  if (symbolId) params.set("symbol", symbolId);
  const query = params.toString();
  return `/repositories/${repositoryId}/code${query ? `?${query}` : ""}`;
}
