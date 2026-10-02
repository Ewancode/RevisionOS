import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi } from "@/test/fakeApi";

import { uploadDocument } from "./queries";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1",
  academic_year_id: "y1",
  code: "MATH111",
  title: "Programming",
  subject_tag: null,
  credits: 15,
  colour: null,
  status: "active",
};
const doc = {
  id: "d1",
  module_id: "m1",
  topic_id: null,
  original_filename: "Vectors.pdf",
  mime: "application/pdf",
  size_bytes: 1000,
  source_tier: "university",
  material_kind: "lecture",
  week: 4,
  status: "ready",
  stage: "ready",
  progress: 100,
  error_code: null,
  page_count: 2,
  created_at: "2026-10-01T12:00:00Z",
};
const pages = [
  {
    page_no: 1,
    markdown: "# Vectors\n\nA vector has magnitude and direction.",
    extraction_method: "text",
    maths_damage_score: 0.02,
    needs_review: false,
    review_note: null,
  },
  {
    page_no: 2,
    markdown: "$$\\mathbf{u} \\cdot \\mathbf{v} = u_1 v_1 + u_2 v_2$$",
    extraction_method: "vision",
    maths_damage_score: 0.9,
    needs_review: true,
    review_note: "subscript on line 2 unclear",
  },
];
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

describe("document page", () => {
  it("shows each page with its image, rendered maths and review notes", async () => {
    fakeApi({
      "GET /api/v1/auth/session": () => [200, session],
      "GET /api/v1/years": () => [200, [year]],
      "GET /api/v1/modules": () => [200, [module]],
      "GET /api/v1/modules/m1": () => [200, module],
      "GET /api/v1/documents/d1": () => [200, doc],
      "GET /api/v1/documents/d1/pages": () => [200, pages],
      "GET /api/v1/ai/budget": () => [200, budget],
    });
    renderAt("/doc/d1");

    await screen.findByRole("heading", { name: "Vectors.pdf" });
    const page2 = await screen.findByRole("article", { name: /page 2/i });
    expect(within(page2).getByText("Transcribed by Claude")).toBeInTheDocument();
    expect(within(page2).getByRole("note")).toHaveTextContent("subscript on line 2 unclear");
    expect(page2.querySelector(".katex")).not.toBeNull();
    expect(within(page2).getByRole("img")).toHaveAttribute("src", "/api/v1/documents/d1/pages/2/preview");
    expect(screen.getByText(/1 page needs checking/)).toBeInTheDocument();
    expect(screen.getByText(/£0\.31 of £10\.00/)).toBeInTheDocument();
  });

  it("saves a hand correction", async () => {
    const { calls } = fakeApi({
      "GET /api/v1/auth/session": () => [200, session],
      "GET /api/v1/years": () => [200, [year]],
      "GET /api/v1/modules": () => [200, [module]],
      "GET /api/v1/modules/m1": () => [200, module],
      "GET /api/v1/documents/d1": () => [200, doc],
      "GET /api/v1/documents/d1/pages": () => [200, pages],
      "GET /api/v1/ai/budget": () => [200, budget],
      "PUT /api/v1/documents/d1/pages/2": (_req, body) => [
        200,
        { ...pages[1], ...(body as object), extraction_method: "corrected", needs_review: false },
      ],
    });
    const user = userEvent.setup();
    renderAt("/doc/d1");

    const page2 = await screen.findByRole("article", { name: /page 2/i });
    await user.click(within(page2).getByRole("button", { name: "Correct" }));
    const editor = within(page2).getByRole("textbox");
    await user.clear(editor);
    await user.type(editor, "u_1 v_1 + u_2 v_2");
    await user.click(within(page2).getByRole("button", { name: "Save correction" }));

    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ markdown: "u_1 v_1 + u_2 v_2" }),
    );
  });
});

describe("citation links", () => {
  it("open the document at the cited page", async () => {
    fakeApi({
      "GET /api/v1/auth/session": () => [200, session],
      "GET /api/v1/years": () => [200, [year]],
      "GET /api/v1/modules": () => [200, [module]],
      "GET /api/v1/modules/m1": () => [200, module],
      "GET /api/v1/documents/d1": () => [200, doc],
      "GET /api/v1/documents/d1/pages": () => [200, pages],
      "GET /api/v1/ai/budget": () => [200, budget],
    });
    renderAt("/doc/d1?page=2");
    const page2 = await screen.findByRole("article", { name: /page 2/i });
    await vi.waitFor(() => expect(page2).toHaveFocus());
  });
});

// --- upload request -------------------------------------------------------------

class FakeXhr {
  static last: FakeXhr | undefined;
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown;
  status = 0;
  responseText = "";
  upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
  }
}

describe("uploadDocument", () => {
  const original = globalThis.XMLHttpRequest;
  afterEach(() => {
    globalThis.XMLHttpRequest = original;
    document.cookie = "__Host-rev_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; Path=/";
  });

  it("sends the raw file with metadata in the query, the CSRF header and progress", async () => {
    globalThis.XMLHttpRequest = FakeXhr as unknown as typeof XMLHttpRequest;
    document.cookie = "__Host-rev_csrf=tok; Secure; Path=/";
    const file = new File(["%PDF-1.7"], "Week 4 Lecture.pdf", { type: "application/pdf" });
    const progress: number[] = [];

    const done = uploadDocument(
      file,
      { moduleId: "m1", sourceTier: "university", materialKind: "lecture", week: 4 },
      (f) => progress.push(f),
    );
    const xhr = FakeXhr.last!;
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 8 });
    xhr.status = 202;
    xhr.responseText = JSON.stringify(doc);
    xhr.onload?.();

    await expect(done).resolves.toMatchObject({ id: "d1" });
    const url = new URL(xhr.url, "https://localhost");
    expect(url.pathname).toBe("/api/v1/documents");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      filename: "Week 4 Lecture.pdf",
      module_id: "m1",
      source_tier: "university",
      material_kind: "lecture",
      week: "4",
    });
    expect(xhr.headers["X-CSRF-Token"]).toBe("tok");
    expect(xhr.body).toBe(file);
    expect(progress).toEqual([0.5]);
  });

  it("turns error envelopes into readable errors", async () => {
    globalThis.XMLHttpRequest = FakeXhr as unknown as typeof XMLHttpRequest;
    const done = uploadDocument(
      new File(["x"], "a.pdf"),
      { moduleId: "m1", sourceTier: "own", materialKind: "notes" },
      () => {},
    );
    const xhr = FakeXhr.last!;
    xhr.status = 409;
    xhr.responseText = JSON.stringify({
      error: { code: "duplicate_upload", message: "You already uploaded this file as “Lecture 1.pdf”.", request_id: "r" },
    });
    xhr.onload?.();
    await expect(done).rejects.toMatchObject({ code: "duplicate_upload", status: 409 });
  });
});
