/**
 * TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas).
 * Keep these in sync when the API contract changes.
 */

export type Uuid = string;
/** ISO-8601 timestamp string. */
export type Timestamp = string;

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
    request_id: string | null;
  };
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  timestamp: Timestamp;
}

export interface ReadinessResponse {
  status: "ok" | "unavailable";
  checks: Record<string, "ok" | "error">;
}

export interface Project {
  id: Uuid;
  name: string;
  description: string | null;
  owner_id: Uuid | null;
  created_at: Timestamp;
  updated_at: Timestamp;
}

export type RepositorySourceType = "github" | "local";

/** pending → queued → cloning → analyzing → indexing → parsing → embedding → completed (or failed). */
export type RepositoryStatus =
  | "pending"
  | "queued"
  | "cloning"
  | "analyzing"
  | "indexing"
  | "parsing"
  | "embedding"
  | "completed"
  | "failed";

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface LanguageStat {
  language: string;
  files: number;
  bytes: number;
}

export interface LastCommit {
  sha: string;
  author_name: string;
  authored_at: Timestamp;
  subject: string;
}

export interface RepositoryMetadata {
  total_files: number;
  total_size_bytes: number;
  indexed_files: number;
  skipped_files: Record<string, number>;
  primary_language: string | null;
  languages: LanguageStat[];
  manifests: string[];
  readme_path: string | null;
  license_path: string | null;
  last_commit: LastCommit | null;
  /** Code-analysis statistics; null for repositories indexed before analysis existed. */
  analysis?: AnalysisSummary | null;
  /** Search-index statistics; null when retrieval is switched off or predates it. */
  retrieval?: RetrievalSummary | null;
}

export interface Repository {
  id: Uuid;
  project_id: Uuid;
  name: string;
  owner: string | null;
  url: string;
  source_type: RepositorySourceType;
  default_branch: string;
  branch: string;
  commit_sha: string | null;
  local_path: string | null;
  status: RepositoryStatus;
  status_message: string | null;
  last_indexed_at: Timestamp | null;
  metadata: RepositoryMetadata | null;
  created_at: Timestamp;
  updated_at: Timestamp;
}

export interface IndexingJob {
  id: Uuid;
  repository_id: Uuid;
  status: JobStatus;
  /** Last pipeline stage reached — tells where a failure happened. */
  stage: RepositoryStatus;
  branch: string;
  commit_sha: string | null;
  files_total: number | null;
  files_processed: number;
  error_message: string | null;
  started_at: Timestamp | null;
  finished_at: Timestamp | null;
  created_at: Timestamp;
  updated_at: Timestamp;
}

export interface RepositoryDetail extends Repository {
  latest_job: IndexingJob | null;
}

export interface RepositoryCreatePayload {
  source_type: RepositorySourceType;
  url: string;
  branch?: string | null;
  name?: string | null;
  project_id?: Uuid | null;
}

// --- Code analysis (Phase 3) ---------------------------------------------------

export type SymbolKind =
  | "function"
  | "method"
  | "class"
  | "component"
  | "interface"
  | "type_alias"
  | "enum"
  | "variable";

export type ParseStatus = "parsed" | "partial" | "failed";
export type RelationshipType = "imports" | "calls" | "inherits" | "renders";
/** confirmed: resolved import to one file. inferred: matched by name. */
export type Confidence = "confirmed" | "inferred";

export interface RetrievalSummary {
  chunks: number;
  chunker_version: number;
  chunk_types: Record<string, number>;
  languages: Record<string, number>;
  bm25: { k1: number; b: number; tokenizer_version: number; terms: number };
  dense: {
    status: "ready" | "disabled" | "empty" | "unavailable";
    provider?: string;
    model?: string;
    dimension?: number;
    vectors?: number;
    skipped?: number;
    store?: string;
    reason?: string;
  };
}

export interface AnalysisSummary {
  analyzer_version: number;
  files_analyzed: number;
  files_by_language: Record<string, number>;
  parse_status: Partial<Record<ParseStatus, number>>;
  symbols_by_kind: Partial<Record<SymbolKind, number>>;
  imports: Partial<Record<"resolved" | "external" | "unresolved", number>>;
  relationships: Partial<Record<RelationshipType, Record<Confidence, number>>>;
  api_calls: number;
  most_imported: { path: string; importers: number }[];
  external_packages: { name: string; files: number }[];
  skipped_files: number;
}

export interface CodeFileSummary {
  path: string;
  language: string | null;
  size_bytes: number;
  line_count: number;
  analyzed: boolean;
  parser: string | null;
  parse_status: ParseStatus | null;
  symbol_count: number;
  import_count: number;
}

export interface FileContent {
  path: string;
  language: string | null;
  size_bytes: number;
  line_count: number;
  content: string;
}

export interface SymbolParameter {
  name: string;
  type: string | null;
  default: string | null;
  kind: string;
  optional: boolean;
}

export interface ApiCallInfo {
  client: string;
  method: string;
  url: string;
  line: number;
}

export interface CodeSymbol {
  id: Uuid;
  file_id: Uuid;
  parent_symbol_id: Uuid | null;
  name: string;
  qualified_name: string;
  kind: SymbolKind;
  start_line: number;
  end_line: number;
  signature: string | null;
  docstring: string | null;
  return_type: string | null;
  is_exported: boolean;
  is_async: boolean;
  parameters: SymbolParameter[];
  decorators: string[];
  metadata: {
    calls?: string[];
    renders?: string[];
    hooks?: string[];
    api_calls?: ApiCallInfo[];
    bases?: string[];
    comment?: string;
    [key: string]: unknown;
  };
}

export interface SymbolSearchResult extends CodeSymbol {
  file_path: string;
}

export interface CodeImport {
  id: Uuid;
  module: string;
  kind: string;
  names: { name: string; alias?: string }[];
  start_line: number;
  end_line: number;
  is_type_only: boolean;
  resolution_status: "resolved" | "external" | "unresolved";
  resolved_path: string | null;
  metadata: {
    confidence?: Confidence;
    strategy?: string;
    package?: string;
    candidates?: string[];
    name_targets?: Record<string, string>;
    [key: string]: unknown;
  };
}

export interface FileDependency {
  relationship_id: Uuid;
  path: string;
  confidence: Confidence;
  weight: number;
  specifiers: string[];
}

export interface ExportInfo {
  name: string;
  local_name?: string;
  kind: string;
  source?: string;
  line?: number;
}

export interface CodeFileDetail {
  path: string;
  language: string;
  size_bytes: number;
  line_count: number;
  content_sha256: string;
  parse_status: ParseStatus;
  symbol_count: number;
  import_count: number;
  metadata: {
    docstring?: string;
    exports?: ExportInfo[];
    api_calls?: ApiCallInfo[];
    syntax_errors?: number;
    comment_lines?: number;
    truncated?: boolean;
    error?: string;
  };
  symbols: CodeSymbol[];
  imports: CodeImport[];
  depends_on: FileDependency[];
  imported_by: FileDependency[];
}

export interface SymbolReference {
  id: Uuid;
  name: string;
  qualified_name: string;
  kind: SymbolKind;
  start_line: number;
  end_line: number;
}

export interface Relationship {
  id: Uuid;
  relationship_type: RelationshipType;
  confidence: Confidence;
  weight: number;
  source_path: string;
  target_path: string;
  source_symbol: SymbolReference | null;
  target_symbol: SymbolReference | null;
  metadata: {
    resolution?: string;
    expressions?: string[];
    lines?: number[];
    [key: string]: unknown;
  };
}
