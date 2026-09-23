"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { CloseIcon } from "@/components/ui/icons";
import { cn } from "@/lib/utils";

import { primaryNavigation, upcomingNavigation } from "./navigation";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className={cn(
          "fixed inset-0 z-30 bg-slate-900/50 transition-opacity lg:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-slate-900 text-slate-300 transition-transform",
          "lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
        aria-label="Sidebar"
      >
        <div className="flex h-16 items-center justify-between px-5">
          <Link href="/dashboard" className="flex items-center gap-2.5" onClick={onClose}>
            <span className="grid size-8 place-items-center rounded-lg bg-indigo-500 text-sm font-bold text-white">
              CS
            </span>
            <span className="text-base font-semibold text-white">CodeSage</span>
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:text-white lg:hidden"
            aria-label="Close navigation"
          >
            <CloseIcon />
          </button>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
          <ul className="space-y-1">
            {primaryNavigation.map(({ label, href, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onClose}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                      active
                        ? "bg-slate-800 text-white"
                        : "hover:bg-slate-800/60 hover:text-white",
                    )}
                  >
                    <Icon />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>

          <div>
            <p className="px-3 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Coming soon
            </p>
            <ul className="mt-2 space-y-1">
              {upcomingNavigation.map(({ label, icon: Icon }) => (
                <li
                  key={label}
                  className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-500"
                >
                  <Icon />
                  {label}
                </li>
              ))}
            </ul>
          </div>
        </nav>

        <div className="border-t border-slate-800 px-5 py-4 text-xs text-slate-500">
          Phase 3 · Code analysis
        </div>
      </aside>
    </>
  );
}
