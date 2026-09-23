import type { Metadata } from "next";
import Link from "next/link";

import { RepositoryList } from "@/components/repositories/repository-list";
import { buttonClassName } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";

export const metadata: Metadata = { title: "Repositories" };

export default function RepositoriesPage() {
  return (
    <>
      <PageHeader
        title="Repositories"
        description="Source code repositories registered for analysis."
        actions={
          <Link href="/repositories/new" className={buttonClassName("primary")}>
            Add repository
          </Link>
        }
      />
      <RepositoryList />
    </>
  );
}
