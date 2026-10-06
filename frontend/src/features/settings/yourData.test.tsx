import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeApi } from "@/test/fakeApi";

import { YourData } from "./YourData";

const job = (over: Record<string, unknown>) => ({
  id: "j1", kind: "export", status: "done", size_bytes: 4_400_000, counts: { questions: 3 },
  error_code: null, error_message: null, created_at: "2026-10-06T09:00:00Z",
  finished_at: "2026-10-06T09:01:00Z", expires_at: "2026-10-13T09:00:00Z", ...over,
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <YourData />
    </QueryClientProvider>,
  );
}

describe("Your data", () => {
  it("lists exports with a download link, and starts a new one", async () => {
    let jobs = [job({})];
    const api = fakeApi({
      "GET /api/v1/export": () => [200, jobs],
      "POST /api/v1/export": () => {
        jobs = [job({ id: "j2", status: "queued", expires_at: null, size_bytes: null }), ...jobs];
        return [202, jobs[0]];
      },
    });
    renderIt();
    const link = await screen.findByRole("link", { name: "Download ZIP" });
    expect(link.getAttribute("href")).toBe("/api/v1/export/j1/file");
    expect(screen.getByText(/Ready \(4\.2 MB\)/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Export my data" }));
    expect(await screen.findByText("Waiting to start…")).toBeTruthy();
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/api/v1/export")).toBe(true);
    // One at a time: both buttons wait for the running job.
    expect((screen.getByRole("button", { name: "Export my data" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows why a restore failed, and when an export has expired", async () => {
    fakeApi({
      "GET /api/v1/export": () => [
        200,
        [
          job({ id: "r1", kind: "restore", status: "failed", error_code: "account_not_empty",
                error_message: "Restore needs an empty account." }),
          job({ id: "j0", expires_at: null, size_bytes: null }),
        ],
      ],
    });
    renderIt();
    expect(await screen.findByText("Restore needs an empty account.")).toBeTruthy();
    expect(screen.getByText("Expired.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Download ZIP" })).toBeNull();
  });
});
