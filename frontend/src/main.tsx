import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Providers } from "./app/providers";
import { router } from "./app/router";
import { applyAppearance, cachedAppearance } from "./lib/theme";
import "./index.css";

// Paint with the last-known theme before the session request returns.
const appearance = cachedAppearance();
if (appearance) applyAppearance(appearance);

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");

createRoot(root).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
