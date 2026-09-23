"use client";

import { useEffect } from "react";

import { Card } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/states";

/** Route-level error boundary for unexpected rendering errors. */
export default function RouteError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <Card>
      <ErrorState title="This page failed to load" error={error} onRetry={retry} />
    </Card>
  );
}
