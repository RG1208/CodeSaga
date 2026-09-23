/**
 * One typed function per backend endpoint. Components call these instead of
 * building URLs, so an API change is fixed in exactly one place.
 */
import { apiRequest } from "./client";
import type {
  CodeFileDetail,
  CodeFileSummary,
  CodeSymbol,
  Confidence,
  FileContent,
  HealthResponse,
  IndexingJob,
  Page,
  PaginationParams,
  Project,
  ReadinessResponse,
  Relationship,
  RelationshipType,
  Repository,
  RepositoryCreatePayload,
  RepositoryDetail,
  RepositoryStatus,
  SymbolKind,
  SymbolSearchResult,
  Uuid,
} from "./types";

interface CallOptions {
  signal?: AbortSignal;
}

export const healthApi = {
  live: (options?: CallOptions) => apiRequest<HealthResponse>("/health", options),
  ready: (options?: CallOptions) => apiRequest<ReadinessResponse>("/health/ready", options),
};

export const projectsApi = {
  list: (params: PaginationParams = {}, options?: CallOptions) =>
    apiRequest<Page<Project>>("/projects", { ...options, query: { ...params } }),

  get: (id: Uuid, options?: CallOptions) =>
    apiRequest<Project>(`/projects/${encodeURIComponent(id)}`, options),
};

export interface RepositoryListParams extends PaginationParams {
  projectId?: Uuid;
  status?: RepositoryStatus;
}

export const repositoriesApi = {
  list: ({ projectId, status, ...params }: RepositoryListParams = {}, options?: CallOptions) =>
    apiRequest<Page<Repository>>("/repositories", {
      ...options,
      query: { ...params, project_id: projectId, status },
    }),

  get: (id: Uuid, options?: CallOptions) =>
    apiRequest<RepositoryDetail>(`/repositories/${encodeURIComponent(id)}`, options),

  /** Validates the URL/path and checks the remote; can take a few seconds. */
  create: (payload: RepositoryCreatePayload) =>
    apiRequest<Repository>("/repositories", { method: "POST", body: payload, timeoutMs: 60_000 }),

  startIndexing: (id: Uuid) =>
    apiRequest<IndexingJob>(`/repositories/${encodeURIComponent(id)}/index`, { method: "POST" }),

  remove: (id: Uuid) =>
    apiRequest<void>(`/repositories/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export interface SymbolSearchParams extends PaginationParams {
  q?: string;
  kind?: SymbolKind;
  pathPrefix?: string;
  exported?: boolean;
}

export interface DependencyParams extends PaginationParams {
  type?: RelationshipType;
  confidence?: Confidence;
  path?: string;
  symbolId?: Uuid;
  direction?: "outgoing" | "incoming" | "both";
}

/** Source-code analysis of one repository. */
export const codeApi = {
  files: (
    repositoryId: Uuid,
    params: { analyzed?: boolean; pathPrefix?: string; limit?: number; offset?: number } = {},
    options?: CallOptions,
  ) =>
    apiRequest<Page<CodeFileSummary>>(`/repositories/${encodeURIComponent(repositoryId)}/files`, {
      ...options,
      query: {
        analyzed: params.analyzed,
        path_prefix: params.pathPrefix,
        limit: params.limit,
        offset: params.offset,
      },
    }),

  content: (repositoryId: Uuid, path: string, options?: CallOptions) =>
    apiRequest<FileContent>(`/repositories/${encodeURIComponent(repositoryId)}/files/content`, {
      ...options,
      query: { path },
    }),

  fileDetail: (repositoryId: Uuid, path: string, options?: CallOptions) =>
    apiRequest<CodeFileDetail>(`/repositories/${encodeURIComponent(repositoryId)}/files/detail`, {
      ...options,
      query: { path },
    }),

  fileSymbols: (repositoryId: Uuid, path: string, options?: CallOptions) =>
    apiRequest<CodeSymbol[]>(`/repositories/${encodeURIComponent(repositoryId)}/files/symbols`, {
      ...options,
      query: { path },
    }),

  searchSymbols: (repositoryId: Uuid, params: SymbolSearchParams = {}, options?: CallOptions) =>
    apiRequest<Page<SymbolSearchResult>>(`/repositories/${encodeURIComponent(repositoryId)}/symbols`, {
      ...options,
      query: {
        q: params.q,
        kind: params.kind,
        path_prefix: params.pathPrefix,
        exported: params.exported,
        limit: params.limit,
        offset: params.offset,
      },
    }),

  dependencies: (repositoryId: Uuid, params: DependencyParams = {}, options?: CallOptions) =>
    apiRequest<Page<Relationship>>(`/repositories/${encodeURIComponent(repositoryId)}/dependencies`, {
      ...options,
      query: {
        type: params.type,
        confidence: params.confidence,
        path: params.path,
        symbol_id: params.symbolId,
        direction: params.direction,
        limit: params.limit,
        offset: params.offset,
      },
    }),
};
