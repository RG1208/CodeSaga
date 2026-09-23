"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { cn } from "@/lib/utils";

import { Header } from "./header";
import { Sidebar } from "./sidebar";

/** Persistent application frame: sidebar navigation, header, and page content. */
export function AppShell({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // The code explorer uses three panes and needs the full width.
  const wide = usePathname().endsWith("/code");

  return (
    <div className="min-h-screen bg-slate-50">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="lg:pl-64">
        <Header onMenuClick={() => setSidebarOpen(true)} />
        <main className={cn("mx-auto px-4 py-8 sm:px-6", wide ? "max-w-[110rem]" : "max-w-6xl")}>{children}</main>
      </div>
    </div>
  );
}
