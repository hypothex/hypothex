import { rename, rm } from "node:fs/promises";
import openapiTS, { COMMENT_HEADER, astToString, type OpenAPI3 } from "openapi-typescript";

type FetchSchema = (input: string | URL, init?: RequestInit) => Promise<Response>;

/** Fetch the protected schema without putting a credential in URLs or diagnostics. */
export async function generateTypes(base: string, token: string | undefined, fetcher: FetchSchema = fetch): Promise<string> {
  let url: URL;
  try {
    const hub = new URL(base);
    if (!["http:", "https:"].includes(hub.protocol) || hub.username || hub.password || hub.search || hub.hash) throw new Error();
    url = new URL("/api/openapi.json", hub);
  } catch { throw new Error("Invalid hub URL"); }
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token !== undefined) {
    if (token.length < 1 || token.length > 4096 || !/^[A-Za-z0-9._~+/-]+=*$/.test(token)) {
      throw new Error("Invalid bearer token format");
    }
    headers.Authorization = `Bearer ${token}`;
  }
  let response: Response;
  try { response = await fetcher(url, { headers, redirect: "error" }); }
  catch { throw new Error("Cannot fetch the OpenAPI schema"); }
  if (!response.ok) {
    throw new Error(`Schema request failed (HTTP ${response.status}); set HYPOTHEX_HUB_TOKEN from hx token`);
  }
  try {
    const schema = await response.json() as OpenAPI3;
    return COMMENT_HEADER + astToString(await openapiTS(schema, { silent: true }));
  } catch { throw new Error("Invalid OpenAPI schema"); }
}

if (import.meta.main) {
  const target = new URL("../src/api/types.ts", import.meta.url);
  const temporary = new URL(`../src/api/.types-${crypto.randomUUID()}.tmp`, import.meta.url);
  try {
    const result = await generateTypes(process.env.HYPOTHEX_HUB_URL ?? "http://127.0.0.1:7777", process.env.HYPOTHEX_HUB_TOKEN);
    await Bun.write(temporary, result);
    await rename(temporary, target);
  } catch (error) {
    console.error(error instanceof Error ? error.message : "Cannot generate API types");
    process.exitCode = 1;
  } finally { await rm(temporary, { force: true }); }
}
