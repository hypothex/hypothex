import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { NavigateContext } from "../../src/pages/components/links";

/** One request the mocked `fetch` saw. */
export interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** A non-200 answer for `mockApi`. */
export class HttpReply {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {}
}

type Handler = unknown | ((call: Call) => unknown);

const realFetch = globalThis.fetch;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Replace `fetch` with a table of canned answers keyed by `"METHOD /path?query"`.
 *
 * A handler may be a value (sent as JSON 200), an `HttpReply`, or a function of the
 * call; a function that throws makes `fetch` reject, like a dropped connection.
 * Unknown keys answer 404. Returns the list of calls, in order.
 */
export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  const fake = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === "string" ? input : input instanceof URL ? `${input.pathname}${input.search}` : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const call = { method, url, body };
    calls.push(call);
    const key = `${method} ${url}`;
    if (!(key in routes)) return json(404, { error: `unmocked ${key}`, type: "StoreError" });
    const handler = routes[key];
    const out = typeof handler === "function" ? await (handler as (c: Call) => unknown)(call) : handler;
    if (out instanceof HttpReply) return json(out.status, out.body);
    return json(200, out);
  };
  globalThis.fetch = fake as unknown as typeof fetch;
  return calls;
}

/** Put the real `fetch` back (call in `afterEach`). */
export function restoreFetch(): void {
  globalThis.fetch = realFetch;
}

/** Replace `navigator.clipboard`; returns the texts written. */
export function mockClipboard(fail = false): string[] {
  const written: string[] = [];
  Object.defineProperty(globalThis.navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: async (text: string) => {
        if (fail) throw new Error("denied");
        written.push(text);
      },
    },
  });
  return written;
}

export interface RenderOpts {
  navigate?: (href: string) => void;
}

/** Render inside a fresh QueryClient (no query retries), with an optional navigate spy. */
export function renderWithClient(ui: ReactElement, opts: RenderOpts = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let tree = <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
  if (opts.navigate) {
    tree = <NavigateContext.Provider value={opts.navigate}>{tree}</NavigateContext.Provider>;
  }
  return { ...render(tree), client };
}
