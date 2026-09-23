"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button, buttonClassName } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, asApiError } from "@/lib/api/client";
import { projectsApi, repositoriesApi } from "@/lib/api/endpoints";
import type { RepositorySourceType } from "@/lib/api/types";
import { useApi } from "@/lib/hooks/use-api";
import { looksLikeGitHubUrl } from "@/lib/repositories";
import { cn } from "@/lib/utils";

const sourceOptions: { value: RepositorySourceType; label: string; hint: string }[] = [
  { value: "github", label: "GitHub URL", hint: "Public repositories only." },
  {
    value: "local",
    label: "Local path",
    hint: "Development mode only. The folder must be a git repository inside an allowed directory.",
  },
];

const inputClassName =
  "block w-full rounded-lg border-0 px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-600 focus:outline-none aria-invalid:ring-rose-400";

function validationMessages(error: ApiError): string[] {
  if (error.code !== "validation_error" || !Array.isArray(error.details)) return [];
  return error.details.map((detail: { loc?: unknown[]; message?: string }) => {
    const field = detail.loc?.slice(1).join(".") || "request";
    return `${field}: ${detail.message ?? "invalid"}`;
  });
}

export function AddRepositoryForm() {
  const router = useRouter();
  const projects = useApi("projects:all", (signal) => projectsApi.list({ limit: 100 }, { signal }));

  const [sourceType, setSourceType] = useState<RepositorySourceType>("github");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [projectId, setProjectId] = useState("");
  const [startIndexing, setStartIndexing] = useState(true);
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const trimmedUrl = url.trim();
  const clientError =
    trimmedUrl === ""
      ? sourceType === "github"
        ? "Enter a GitHub repository URL."
        : "Enter the absolute path of a local git repository."
      : sourceType === "github" && !looksLikeGitHubUrl(trimmedUrl)
        ? "Use the form https://github.com/owner/repository"
        : sourceType === "local" && !trimmedUrl.startsWith("/")
          ? "Use an absolute path, e.g. /home/you/projects/my-repo"
          : null;
  const showClientError = touched && clientError !== null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (clientError) return;

    setSubmitting(true);
    setError(null);
    try {
      const repository = await repositoriesApi.create({
        source_type: sourceType,
        url: trimmedUrl,
        branch: branch.trim() || null,
        project_id: projectId || null,
      });
      if (startIndexing) {
        // The details page offers a "Start indexing" button if this fails.
        await repositoriesApi.startIndexing(repository.id).catch(() => undefined);
      }
      router.push(`/repositories/${repository.id}`);
    } catch (caught) {
      setError(asApiError(caught));
      setSubmitting(false);
    }
  }

  const activeSource = sourceOptions.find((option) => option.value === sourceType)!;

  return (
    <div className="max-w-2xl">
      <Card>
        <form onSubmit={handleSubmit} noValidate className="space-y-6 p-6">
          <fieldset>
            <legend className="text-sm font-medium text-slate-900">Source</legend>
            <div className="mt-2 inline-flex rounded-lg bg-slate-200/80 p-1">
              {sourceOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={sourceType === option.value}
                  onClick={() => {
                    setSourceType(option.value);
                    setTouched(false);
                    setError(null);
                  }}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    sourceType === option.value
                      ? "bg-white text-indigo-700 shadow-sm ring-1 ring-slate-300"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </fieldset>

          <div>
            <label htmlFor="repository-url" className="text-sm font-medium text-slate-900">
              {sourceType === "github" ? "Repository URL" : "Repository path"}
            </label>
            <input
              id="repository-url"
              name="url"
              type={sourceType === "github" ? "url" : "text"}
              autoComplete="off"
              spellCheck={false}
              placeholder={
                sourceType === "github"
                  ? "https://github.com/owner/repository"
                  : "/home/you/projects/my-repo"
              }
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={showClientError}
              aria-describedby="repository-url-hint"
              className={cn(inputClassName, "mt-2 font-mono")}
            />
            <p
              id="repository-url-hint"
              className={cn("mt-1.5 text-xs", showClientError ? "text-rose-600" : "text-slate-500")}
            >
              {showClientError ? clientError : activeSource.hint}
            </p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2">
            <div>
              <label htmlFor="repository-branch" className="text-sm font-medium text-slate-900">
                Branch <span className="font-normal text-slate-500">(optional)</span>
              </label>
              <input
                id="repository-branch"
                name="branch"
                type="text"
                autoComplete="off"
                spellCheck={false}
                placeholder="Default branch"
                value={branch}
                onChange={(event) => setBranch(event.target.value)}
                className={cn(inputClassName, "mt-2 font-mono")}
              />
            </div>

            <div>
              <label htmlFor="repository-project" className="text-sm font-medium text-slate-900">
                Project
              </label>
              <select
                id="repository-project"
                name="project"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                disabled={projects.status === "loading"}
                className={cn(inputClassName, "mt-2 bg-white")}
              >
                <option value="">Default project</option>
                {projects.status === "success" &&
                  projects.data.items
                    .filter((project) => project.name !== "Default")
                    .map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
              </select>
            </div>
          </div>

          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={startIndexing}
              onChange={(event) => setStartIndexing(event.target.checked)}
              className="mt-0.5 size-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
            />
            <span className="text-sm">
              <span className="font-medium text-slate-900">Start indexing right away</span>
              <span className="block text-slate-500">
                Clone, analyze and index the repository in the background.
              </span>
            </span>
          </label>

          {error && (
            <div role="alert" className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800">
              <p className="font-medium">{error.message}</p>
              {validationMessages(error).map((message) => (
                <p key={message} className="mt-1">
                  {message}
                </p>
              ))}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 border-t border-slate-100 pt-5">
            <Link href="/repositories" className={buttonClassName("secondary")}>
              Cancel
            </Link>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Checking repository…" : "Add repository"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
