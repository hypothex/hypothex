import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { type StreamStatus, StreamStatusContext } from "../src/api/events";
import { createQueryClient } from "../src/api/queries";
import { createAppRouter } from "../src/router";

/**
 * Render the whole app (shell + routes) at `path` with an in-memory history.
 * Mock `fetch` first (see test/api/fetch-mock.ts) if the page loads data. `streamStatus`
 * stands in for the live-update stream (no socket is opened).
 */
export function renderApp(
  path: string,
  { streamStatus = "ready" }: { streamStatus?: StreamStatus } = {},
): {
  router: ReturnType<typeof createAppRouter>;
  queryClient: QueryClient;
} {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <StreamStatusContext.Provider value={streamStatus}>
        <RouterProvider router={router} />
      </StreamStatusContext.Provider>
    </QueryClientProvider>,
  );
  return { router, queryClient };
}
