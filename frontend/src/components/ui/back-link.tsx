import Link from "next/link";

import { ArrowLeftIcon } from "./icons";

export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900"
    >
      <ArrowLeftIcon className="size-4" />
      {label}
    </Link>
  );
}
