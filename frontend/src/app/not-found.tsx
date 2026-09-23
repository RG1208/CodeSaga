import Link from "next/link";

import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/states";

export default function NotFound() {
  return (
    <Card>
      <EmptyState
        title="Page not found"
        description={
          <Link href="/dashboard" className="font-medium text-indigo-600 hover:text-indigo-500">
            Back to the dashboard
          </Link>
        }
      />
    </Card>
  );
}
