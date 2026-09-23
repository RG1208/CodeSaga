import type { Metadata } from "next";

import { RepositoryDetails } from "@/components/repositories/repository-details";

export const metadata: Metadata = { title: "Repository" };

export default async function RepositoryDetailsPage({
  params,
}: PageProps<"/repositories/[repositoryId]">) {
  const { repositoryId } = await params;
  return <RepositoryDetails repositoryId={repositoryId} />;
}
