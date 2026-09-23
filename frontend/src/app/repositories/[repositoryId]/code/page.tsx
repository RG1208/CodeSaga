import type { Metadata } from "next";
import { Suspense } from "react";

import { CodeExplorer } from "@/components/code/code-explorer";
import { LoadingState } from "@/components/ui/states";

export const metadata: Metadata = { title: "Code" };

export default async function RepositoryCodePage({ params }: PageProps<"/repositories/[repositoryId]/code">) {
  const { repositoryId } = await params;
  return (
    // useSearchParams (file/symbol selection lives in the URL) needs a Suspense boundary.
    <Suspense fallback={<LoadingState label="Loading code explorer…" />}>
      <CodeExplorer repositoryId={repositoryId} />
    </Suspense>
  );
}
