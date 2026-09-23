"use client";

import { MenuIcon } from "@/components/ui/icons";

import { ApiStatus } from "./api-status";

export function Header({ onMenuClick }: { onMenuClick: () => void }) {
  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-slate-200 bg-white/80 px-4 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        className="-ml-1 rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden"
        aria-label="Open navigation"
      >
        <MenuIcon />
      </button>
      <p className="text-sm text-slate-500">
        <span className="font-medium text-slate-900">CodeSage</span>
        <span className="hidden sm:inline"> · Codebase intelligence &amp; review</span>
      </p>
      <div className="ml-auto">
        <ApiStatus />
      </div>
    </header>
  );
}
