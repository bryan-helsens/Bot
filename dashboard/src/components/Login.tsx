import { useState } from "react";
import { api, setToken } from "../api/client";

/** Login screen shown when the API requires authentication. */
export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api.login(username, password);
      setToken(r.access_token);
      onSuccess();
    } catch {
      setErr("Invalid credentials.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="panel login-card" onSubmit={submit}>
        <h1>🤖 QuantBot</h1>
        <p className="hint">This dashboard is protected. Sign in to continue.</p>
        <input
          className="cap-input"
          placeholder="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <input
          className="cap-input"
          type="password"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        {err && <div className="note err">{err}</div>}
        <button className="btn-buy" disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
