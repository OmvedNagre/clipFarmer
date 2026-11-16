import { useState, useEffect } from "react";
import { api } from "../api";
export default function AuthGate({ children }) {
  const [state, setState] = useState(null),
    [token, setToken] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/auth/status")
      .then(setState)
      .catch((e) => setError(e.message));
  }, []);
  if (state?.authenticated || state?.required === false) return children;
  async function unlock(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      setToken("");
      setState({ authenticated: true });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-screen">
      <section className="panel">
        <span className="eyebrow">VI CLIPFORGE</span>
        <h1>{state ? "Unlock workspace" : "Connecting…"}</h1>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        {state && (
          <form onSubmit={unlock} className="stack-form">
            <label>
              Workspace access token
              <input
                type="password"
                autoComplete="current-password"
                required
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
            <button className="primary" disabled={busy}>
              Unlock
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
