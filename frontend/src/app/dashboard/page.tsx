import type { Metadata } from "next";

import { DashboardOverview } from "@/components/dashboard/dashboard-overview";
import { PageHeader } from "@/components/ui/page-header";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="An overview of the projects and repositories in CodeSage."
      />
      <DashboardOverview />
    </>
  );
}
