import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi } from "@/test/fakeApi";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1",
  academic_year_id: "y1",
  code: "MATH101",
  title: "Calculus I",
  subject_tag: null,
  credits: 15,
  colour: null,
  status: "active",
};
const result = {
  query: "ratio test",
  scope_used: "all",
  widened: false,
  passages: [
    {
      chunk_id: "c1",
      document_id: "d1",
      filename: "MATH101_notes.pdf",
      module_id: "m1",
      module_code: "MATH101",
      page_no: 91,
      heading_path: "Chapter 7 › Series",
      content: "**Theorem 7.12** (Ratio Test). If $|a_{n+1}/a_n| \\le r < 1$ then the series converges.",
      source_tier: "university",
      score: 0.02,
      matched: "both",
    },
  ],
  modules: [],
  topics: [],
  documents: [],
};
const base = {
  "GET /api/v1/auth/session": () => [200, session] as [number, unknown],
  "GET /api/v1/years": () => [200, [year]] as [number, unknown],
  "GET /api/v1/modules": () => [200, [module]] as [number, unknown],
};

function renderAt(path: string) {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("search", () => {
  it("shows passages with maths and links to the exact page", async () => {
    const { calls } = fakeApi({ ...base, "GET /api/v1/search": () => [200, result] });
    renderAt("/search?q=ratio%20test");

    const link = await screen.findByRole("link", { name: "MATH101_notes.pdf — page 91" });
    expect(link).toHaveAttribute("href", "/doc/d1?page=91");
    const card = link.closest("li")!;
    expect(within(card).getByText("Chapter 7 › Series")).toBeInTheDocument();
    expect(card.querySelector(".katex")).not.toBeNull();
    expect(calls.some((c) => c.path === "/api/v1/search")).toBe(true);
  });

  it("says so when nothing matches", async () => {
    fakeApi({ ...base, "GET /api/v1/search": () => [200, { ...result, passages: [] }] });
    renderAt("/search?q=quaternions");
    expect(await screen.findByText("No matches in your materials.")).toBeInTheDocument();
  });

  it("Ctrl+K focuses the sidebar search and Enter opens results", async () => {
    fakeApi({ ...base, "GET /api/v1/search": () => [200, result] });
    const user = userEvent.setup();
    const router = renderAt("/");
    const box = await screen.findByRole("searchbox", { name: "Search your materials" });

    await user.keyboard("{Control>}k{/Control}");
    expect(box).toHaveFocus();
    await user.type(box, "ratio test{Enter}");

    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/search"));
    expect(router.state.location.search).toMatchObject({ q: "ratio test" });
  });
});
