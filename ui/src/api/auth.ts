/** Per-tab transport credential. Tokens never enter URLs, query keys, or React snapshots. */
export const TOKEN_KEY = "hx-transport-token";
type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export interface AuthSnapshot {
  status: "validating" | "locked" | "unlocked";
  generation: number;
}
export interface Credential {
  token: string | null;
  generation: number;
  signal: AbortSignal;
}

function sessionStore(): StorageLike | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

/** Replacing or rejecting a credential synchronously cancels all work of its generation. */
export class AuthStore {
  private token: string | null = null;
  private state: AuthSnapshot = { status: "validating", generation: 0 };
  private controller = new AbortController();
  private listeners = new Set<() => void>();
  private resets = new Set<() => void>();

  constructor(private storage: StorageLike | null = sessionStore()) {
    try {
      this.token = storage?.getItem(TOKEN_KEY) || null;
    } catch {
      // Storage is optional; a denied read starts with the no-auth probe.
    }
  }

  snapshot = (): AuthSnapshot => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  onReset = (listener: () => void): (() => void) => {
    this.resets.add(listener);
    return () => { this.resets.delete(listener); };
  };

  capture(): Credential {
    return { token: this.token, generation: this.state.generation, signal: this.controller.signal };
  }

  current(generation: number): boolean {
    return generation === this.state.generation;
  }

  private publish(status: AuthSnapshot["status"]): void {
    this.state = { ...this.state, status };
    this.listeners.forEach((listener) => listener());
  }

  private replace(token: string | null): void {
    this.controller.abort();
    this.controller = new AbortController();
    this.token = token;
    this.state = { status: "validating", generation: this.state.generation + 1 };
    try {
      this.storage?.removeItem(TOKEN_KEY);
      this.storage?.removeItem("hx-ws-sequence");
    } catch {
      // Optional persistence cannot prevent cancellation and clearing in-memory data.
    }
    this.resets.forEach((reset) => reset());
  }

  select(token: string | null): number {
    this.replace(token);
    this.publish("validating");
    return this.state.generation;
  }

  accept(generation: number): void {
    if (!this.current(generation)) return;
    try {
      if (this.token) this.storage?.setItem(TOKEN_KEY, this.token);
    } catch {
      // A full or disabled store leaves the validated credential in memory only.
    }
    this.publish("unlocked");
  }

  lock(generation: number): void {
    if (!this.current(generation)) return;
    this.replace(null);
    this.publish("locked");
  }
}

export const auth = new AuthStore();
