import Link from "next/link";

import type { Repository } from "@/lib/api/types";
import { repositoryFullName, shortSha } from "@/lib/repositories";
import { formatRelativeTime } from "@/lib/utils";

import { RepositorySourceBadge, RepositoryStatusBadge } from "./repository-status-badge";

export function RepositoryTable({ repositories }: { repositories: Repository[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-500 uppercase">
          <tr>
            <th scope="col" className="px-5 py-3">Repository</th>
            <th scope="col" className="px-5 py-3">Source</th>
            <th scope="col" className="px-5 py-3">Branch</th>
            <th scope="col" className="px-5 py-3">Commit</th>
            <th scope="col" className="px-5 py-3">Status</th>
            <th scope="col" className="px-5 py-3">Last indexed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {repositories.map((repository) => (
            <tr key={repository.id} className="hover:bg-slate-50">
              <td className="max-w-xs px-5 py-3">
                <Link
                  href={`/repositories/${repository.id}`}
                  className="font-medium text-slate-900 hover:text-indigo-600"
                >
                  {repositoryFullName(repository)}
                </Link>
                <p className="truncate text-xs text-slate-500" title={repository.url}>
                  {repository.url}
                </p>
              </td>
              <td className="px-5 py-3">
                <RepositorySourceBadge source={repository.source_type} />
              </td>
              <td className="px-5 py-3 font-mono text-xs text-slate-600">{repository.branch}</td>
              <td className="px-5 py-3 font-mono text-xs text-slate-600">
                {shortSha(repository.commit_sha)}
              </td>
              <td className="px-5 py-3">
                <RepositoryStatusBadge status={repository.status} />
              </td>
              <td className="px-5 py-3 whitespace-nowrap text-slate-500">
                {repository.last_indexed_at ? formatRelativeTime(repository.last_indexed_at) : "Never"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
