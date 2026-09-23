import React, { useEffect, useState } from "react";

import { getUsers } from "@/lib/api";
import type { User } from "@/types";

import { UserCard } from "./UserCard";

export function UserList({ title }: { title: string }): JSX.Element {
  const [users, setUsers] = useState<User[]>([]);

  useEffect(() => {
    getUsers().then(setUsers);
  }, []);

  return (
    <section>
      <h2>{title}</h2>
      <ul>
        {users.map((user) => (
          <UserCard key={user.id} user={user} />
        ))}
      </ul>
    </section>
  );
}

export class LegacyList extends React.Component {
  render() {
    return <UserList title="Legacy" />;
  }
}

export default UserList;
