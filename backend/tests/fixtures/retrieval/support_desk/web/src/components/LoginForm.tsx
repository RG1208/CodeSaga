import { useState } from "react";

import { login } from "../api/client";

interface Props {
  onSignedIn: (token: string) => void;
}

/** Email and password form that signs an agent in. */
export function LoginForm({ onSignedIn }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    try {
      const { token } = await login(email, password);
      onSignedIn(token);
    } catch {
      setError("Sign in failed");
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      {error && <p role="alert">{error}</p>}
      <button type="submit">Sign in</button>
    </form>
  );
}

export default LoginForm;
