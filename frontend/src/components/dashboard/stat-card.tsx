import type { ComponentType, ReactNode, SVGProps } from "react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/states";

interface StatCardProps {
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** `undefined` renders a loading skeleton. */
  value: ReactNode | undefined;
  hint?: string;
}

export function StatCard({ label, icon: Icon, value, hint }: StatCardProps) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-slate-500">
        <p className="text-sm font-medium">{label}</p>
        <Icon />
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
        {value === undefined ? <Skeleton className="h-9 w-16" /> : value}
      </div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </Card>
  );
}
