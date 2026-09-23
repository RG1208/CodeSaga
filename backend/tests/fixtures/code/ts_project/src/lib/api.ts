import axios from "axios";
import type { User } from "../types";

const BASE = "/api";

/**
 * Load all users.
 */
export async function getUsers(): Promise<User[]> {
  const response = await fetch("/api/users");
  return response.json();
}

export const createUser = (name: string, role = "member") =>
  axios.post(`${BASE}/users/${name}`, { role });

export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  async remove(id: string): Promise<void> {
    await fetch(`/api/users/${id}`, { method: "DELETE" });
    this.log(id);
  }

  private log(message: string) {
    console.log(message);
  }
}

export default ApiClient;
