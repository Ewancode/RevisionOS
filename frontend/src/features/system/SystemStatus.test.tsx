import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SystemStatus } from "./SystemStatus";

function renderWithQuery() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SystemStatus />
    </QueryClientProvider>,
  );
}

function stubFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("SystemStatus", () => {
  it("shows every service as OK when the API is ready", async () => {
    const fetchMock = stubFetch(200, {
      status: "ready",
      checks: { database: "ok", redis: "ok" },
    });
    renderWithQuery();

    expect(await screen.findByText(/all services ready/i)).toBeInTheDocument();
    expect(screen.getAllByText("OK")).toHaveLength(2);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/v1/health/ready");
  });

  it("names the failing service when the API is not ready (503)", async () => {
    stubFetch(503, { status: "not_ready", checks: { database: "unavailable", redis: "ok" } });
    renderWithQuery();

    expect(await screen.findByText(/degraded/i)).toBeInTheDocument();
    const dbRow = screen.getByText("Database").closest("li");
    expect(dbRow).toHaveTextContent("Unavailable");
  });

  it("shows an alert when the API cannot be reached", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    renderWithQuery();

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach the api/i);
  });
});
