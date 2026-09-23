import type { Metadata } from "next";

import { AddRepositoryForm } from "@/components/repositories/add-repository-form";
import { BackLink } from "@/components/ui/back-link";
import { PageHeader } from "@/components/ui/page-header";

export const metadata: Metadata = { title: "Add repository" };

export default function NewRepositoryPage() {
  return (
    <>
      <BackLink href="/repositories" label="All repositories" />
      <PageHeader
        title="Add repository"
        description="CodeSage clones the repository and reads its files. Repository code is never executed."
      />
      <AddRepositoryForm />
    </>
  );
}
