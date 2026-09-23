import type { ComponentType, SVGProps } from "react";

import {
  ChatIcon,
  DashboardIcon,
  GraphIcon,
  RepositoryIcon,
  ReviewIcon,
} from "@/components/ui/icons";

export interface NavItem {
  label: string;
  href: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

export const primaryNavigation: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: DashboardIcon },
  { label: "Repositories", href: "/repositories", icon: RepositoryIcon },
];

/** Shown disabled in the sidebar so the roadmap is visible; not implemented yet. */
export const upcomingNavigation: Omit<NavItem, "href">[] = [
  { label: "Ask the codebase", icon: ChatIcon },
  { label: "Code review", icon: ReviewIcon },
  { label: "Impact analysis", icon: GraphIcon },
];
