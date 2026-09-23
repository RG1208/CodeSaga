import type { User } from "@/types";

interface Props {
  user: User;
  compact?: boolean;
}

export const UserCard = ({ user, compact = false }: Props) => (
  <li className={compact ? "compact" : ""}>{user.name}</li>
);
