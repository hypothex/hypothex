import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/palette.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AuthGate } from "./api/AuthGate";
import { LiveUpdates } from "./api/events";
import { createQueryClient } from "./api/queries";
import { createAppRouter } from "./router";

const queryClient = createQueryClient();
const router = createAppRouter();

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <LiveUpdates>
          <RouterProvider router={router} />
        </LiveUpdates>
      </AuthGate>
    </QueryClientProvider>
  </StrictMode>,
);
