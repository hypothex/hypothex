import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { auth } from "./auth";
import { api, ApiError } from "./client";
import { clearSessionQueries } from "./queries";
import "../shell/kept.css";

/** Validate through a protected read before mounting any page or live query. */
export function AuthGate({ children }: { children: ReactNode }) {
  const state = useSyncExternalStore(auth.subscribe, auth.snapshot);
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const [failed, setFailed] = useState(false);

  async function validate(generation: number): Promise<void> {
    try {
      await api.projects();
      auth.accept(generation);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      // Request's 401 may already have locked this generation. Never display response text.
      if (auth.current(generation)) {
        auth.lock(generation);
        setFailed(true);
      } else if (error instanceof ApiError && error.status === 401 && auth.snapshot().generation === generation + 1) {
        setFailed(true);
      }
    }
  }

  useEffect(() => auth.onReset(() => clearSessionQueries(qc)), [qc]);
  // Validate the starting credential once. StrictMode runs mount effects twice; a second
  // request still in flight when the page navigates fails and would lock (and forget) the
  // credential the first one accepted.
  const started = useRef<number | null>(null);
  useEffect(() => {
    const generation = auth.snapshot().generation;
    if (started.current === generation) return;
    started.current = generation;
    void validate(generation);
  }, []);

  if (state.status === "unlocked") return <>{children}</>;
  return (
    <main className="auth-gate">
      <form className="auth-box" onSubmit={(event) => {
        event.preventDefault();
        const supplied = token;
        setToken("");
        setFailed(false);
        const generation = auth.select(supplied || null);
        void validate(generation);
      }}>
        <h1>Hypothex</h1>
        <label htmlFor="hx-token">Token</label>
        <input
          id="hx-token"
          className="auth-in"
          type="password"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <button type="submit" className="btn primary">Unlock</button>
        {state.status === "validating" && <p role="status">Connecting…</p>}
        {failed && state.status === "locked" && <p role="alert">Unable to unlock. Check token and connection.</p>}
      </form>
    </main>
  );
}
