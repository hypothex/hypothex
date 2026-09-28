import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { createQueryClient } from "../src/api/queries";
import { createAppRouter } from "../src/router";

/**
 * Render the whole app (shell + routes) at `path` with an in-memory history.
 * Mock `fetch` first (see test/api/fetch-mock.ts) if the page loads data.
 */
export function renderApp(path: string): {
  router: ReturnType<typeof createAppRouter>;
  queryClient: QueryClient;
} {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, queryClient };
}
