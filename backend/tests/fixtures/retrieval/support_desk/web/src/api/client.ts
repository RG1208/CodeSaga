const BASE_URL = "/api";

export interface ApiError {
  status: number;
  message: string;
}

/** Send a JSON request to the support desk API. */
export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw { status: response.status, message: await response.text() } satisfies ApiError;
  }
  return (await response.json()) as T;
}

export const login = (email: string, password: string) =>
  apiRequest<{ token: string }>("/login", { method: "POST", body: JSON.stringify({ email, password }) });
