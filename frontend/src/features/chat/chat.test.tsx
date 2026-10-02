import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi } from "@/test/fakeApi";

import { parseSse } from "./queries";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const budget = {
  currency: "GBP",
  spent_today: 0.04,
  spent_this_month: 0.31,
  daily_cap: 2,
  monthly_cap: 10,
  warning: false,
  exhausted: false,
  configured: true,
};
const conversation = {
  id: "c1",
  title: "Ratio test",
  module_id: null,
  topic_id: null,
  created_at: "2026-10-02T10:00:00Z",
  updated_at: "2026-10-02T10:00:00Z",
};
const citation = {
  n: 1,
  document_id: "d1",
  filename: "MATH101_notes.pdf",
  page_no: 91,
  source_tier: "university",
  module_code: "MATH101",
  heading_path: "Chapter 7 › Series",
  quote: "Ratio Test",
};
const question = {
  id: "m1",
  role: "user",
  content: "Where is the ratio test?",
  citations: [],
  provenance: [],
  steps: [],
  status: "complete",
  error_code: null,
  created_at: "2026-10-02T10:00:00Z",
  actions: [],
};
const answer = {
  ...question,
  id: "m2",
  role: "assistant",
  content: "Theorem 7.12 states it: if $|a_{n+1}/a_n| \\le r < 1$ the series converges. [[1]](#cite-1)",
  citations: [citation],
  provenance: ["university"],
  steps: ["Searching your materials"],
};

const base = {
  "GET /api/v1/auth/session": () => [200, session] as [number, unknown],
  "GET /api/v1/years": () => [200, [year]] as [number, unknown],
  "GET /api/v1/modules": () => [200, []] as [number, unknown],
  "GET /api/v1/ai/budget": () => [200, budget] as [number, unknown],
  "GET /api/v1/conversations": () => [200, [conversation]] as [number, unknown],
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

function sse(...events: [string, unknown][]) {
  const body = events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("parseSse", () => {
  it("keeps an unfinished frame for the next chunk", () => {
    const first = parseSse('event: delta\ndata: {"text":"Hel"}\n\nevent: delta\ndata: {"te');
    expect(first.events).toEqual([{ event: "delta", data: { text: "Hel" } }]);
    const second = parseSse(first.rest + 'xt":"lo"}\n\n');
    expect(second.events).toEqual([{ event: "delta", data: { text: "lo" } }]);
    expect(second.rest).toBe("");
  });
});

describe("assistant", () => {
  it("shows answers with maths, page citations, sources and where they came from", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/conversations/c1": () => [200, { ...conversation, messages: [question, answer] }],
    });
    renderAt("/chat/c1");

    const reply = await screen.findByRole("article", { name: "Claude's answer" });
    expect(reply.querySelector(".katex")).not.toBeNull();
    const chip = within(reply).getByRole("link", { name: "Source 1: MATH101_notes.pdf — page 91" });
    expect(chip).toHaveAttribute("href", "/doc/d1?page=91");
    const sources = within(reply).getByRole("region", { name: "Sources" });
    expect(within(sources).getByRole("link", { name: "MATH101_notes.pdf — page 91" })).toBeInTheDocument();
    expect(within(reply).getByText("From your university material")).toBeInTheDocument();
  });

  it("badges answers that are not from your materials", async () => {
    const general = { ...answer, content: "From general knowledge.", citations: [], provenance: ["general"] };
    fakeApi({
      ...base,
      "GET /api/v1/conversations/c1": () => [200, { ...conversation, messages: [question, general] }],
    });
    renderAt("/chat/c1");
    expect(await screen.findByText("General knowledge — not from your materials")).toBeInTheDocument();
  });

  it("streams an answer, then shows the saved copy", async () => {
    let saved = false;
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/conversations/c1": () => [
        200,
        { ...conversation, messages: saved ? [question, answer] : [] },
      ],
      "POST /api/v1/conversations/c1/messages": () => {
        saved = true;
        return [
          200,
          sse(
            ["status", { text: "Searching your materials" }],
            ["delta", { text: "Theorem 7.12 " }],
            ["delta", { text: "states it." }],
            ["done", answer],
          ),
        ];
      },
    });
    const user = userEvent.setup();
    renderAt("/chat/c1");

    const box = await screen.findByRole("textbox", { name: "Ask about your materials" });
    await user.type(box, "Where is the ratio test?{Enter}");

    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ content: "Where is the ratio test?" }),
    );
    // The saved answer (with its citation) replaces the streamed text, once.
    expect(await screen.findByRole("link", { name: /Source 1/ })).toBeInTheDocument();
    expect(screen.getAllByText("Where is the ratio test?")).toHaveLength(1);
  });

  it("a new conversation starts from the composer", async () => {
    const { calls } = fakeApi({
      ...base,
      "POST /api/v1/conversations": () => [201, conversation],
      "GET /api/v1/conversations/c1": () => [200, { ...conversation, messages: [question, answer] }],
      "POST /api/v1/conversations/c1/messages": () => [200, sse(["done", answer])],
    });
    const user = userEvent.setup();
    const router = renderAt("/chat");

    await user.type(await screen.findByRole("textbox", { name: "Ask about your materials" }), "Ratio test?{Enter}");
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/chat/c1"));
    expect(calls.find((c) => c.path === "/api/v1/conversations" && c.method === "POST")?.body).toEqual({});
    // The answer started before navigating lands in the new conversation.
    expect(await screen.findByRole("link", { name: /Source 1/ })).toBeInTheDocument();
  });

  it("asks you before deleting anything Claude requested", async () => {
    const action = {
      id: "p1",
      action: "delete_document",
      preview: "Delete “Week 3.pdf”? It moves to the trash.",
      status: "pending",
      expires_at: "2026-10-02T10:10:00Z",
    };
    const withAction = { ...answer, content: "Please confirm.", citations: [], actions: [action] };
    let status = "pending";
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/conversations/c1": () => [
        200,
        { ...conversation, messages: [question, { ...withAction, actions: [{ ...action, status }] }] },
      ],
      "POST /api/v1/pending-actions/p1/confirm": () => {
        status = "confirmed";
        return [200, { ...action, status }];
      },
    });
    const user = userEvent.setup();
    renderAt("/chat/c1");

    const card = await screen.findByRole("group", { name: "Deletion request" });
    expect(card).toHaveTextContent("Delete “Week 3.pdf”?");
    await user.click(within(card).getByRole("button", { name: "Delete" }));
    expect(calls.some((c) => c.path === "/api/v1/pending-actions/p1/confirm")).toBe(true);
    expect(await within(card).findByText(/Deleted\. You can restore it/)).toBeInTheDocument();
  });
});

describe("usage dashboard", () => {
  it("shows totals, the daily chart and breakdowns", async () => {
    const usage = {
      currency: "GBP",
      days: 30,
      since: "2026-09-03",
      totals: {
        requests: 12,
        blocked_requests: 1,
        input_tokens: 40000,
        output_tokens: 5000,
        cache_read_tokens: 20000,
        cache_write_tokens: 0,
        cost: 0.1234,
      },
      by_feature: [{ key: "chat", label: "Assistant", requests: 12, tokens: 45000, cost: 0.1234 }],
      by_model: [{ key: "claude-sonnet-5-5", label: "Sonnet", requests: 12, tokens: 45000, cost: 0.1234 }],
      by_module: [{ key: "MATH101", label: "MATH101", requests: 12, tokens: 45000, cost: 0.1234 }],
      by_day: [
        { day: "2026-10-01", requests: 0, cost: 0 },
        { day: "2026-10-02", requests: 12, cost: 0.1234 },
      ],
    };
    fakeApi({ ...base, "GET /api/v1/ai/usage": () => [200, usage] });
    renderAt("/usage");

    expect(await screen.findByText("£0.1234", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /AI cost per day/ })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Sonnet" })).toBeInTheDocument();
  });
});
