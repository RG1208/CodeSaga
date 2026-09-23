import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { RepositorySourceType, RepositoryStatus } from "@/lib/api/types";
import { isActiveStatus } from "@/lib/repositories";

export const statusDisplay: Record<
  RepositoryStatus,
  { label: string; tone: BadgeTone }
> = {
  pending: { label: "Not indexed", tone: "neutral" },
  queued: { label: "Queued", tone: "info" },
  cloning: { label: "Cloning", tone: "info" },
  analyzing: { label: "Analyzing", tone: "info" },
  indexing: { label: "Indexing", tone: "info" },
  parsing: { label: "Parsing", tone: "info" },
  embedding: { label: "Building search index", tone: "info" },
  completed: { label: "Indexed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

export function RepositoryStatusBadge({
  status,
}: {
  status: RepositoryStatus;
}) {
  const { label, tone } = statusDisplay[status];
  return (
    <Badge tone={tone}>
      {isActiveStatus(status) && (
        <span
          aria-hidden="true"
          className="size-2.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent"
        />
      )}
      {label}
    </Badge>
  );
}

const sourceLabels: Record<RepositorySourceType, string> = {
  github: "GitHub",
  local: "Local",
};

export function RepositorySourceBadge({
  source,
}: {
  source: RepositorySourceType;
}) {
  return <Badge>{sourceLabels[source]}</Badge>;
}
