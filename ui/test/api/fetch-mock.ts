import { mock } from "bun:test";

export interface Call {
  url: string;
  method: string;
  body: unknown;
}

/**
 * Replace `fetch` with a stub that answers every request with `status` and `body`
 * (objects are sent as JSON, strings as text) and records each call.
 */
export function mockFetch(body: unknown, status = 200): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    });
    const text = typeof body === "string" ? body : JSON.stringify(body);
    return new Response(text, { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

/**
 * Route-aware variant: `routes` maps a URL path prefix to the JSON body to return; the
 * longest prefix wins. A `null` body, or no matching prefix, answers 404.
 */
export function mockRoutes(routes: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET", body: undefined });
    const key = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((prefix) => url.startsWith(prefix));
    if (key === undefined || routes[key] === null) {
      return new Response(JSON.stringify({ error: "no route", type: "StoreError" }), { status: 404 });
    }
    return new Response(JSON.stringify(routes[key]), { status: 200 });
  }) as unknown as typeof fetch;
  return calls;
}
