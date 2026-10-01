import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, unwrap } from "./client";

// __Host- cookies need Secure and Path=/ (the test DOM runs on https://localhost).
function setCookie(value: string) {
  document.cookie = `${value}; Secure; Path=/`;
}

afterEach(() => {
  setCookie("__Host-rev_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT");
});

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  it("sends the CSRF cookie as a header on unsafe requests only", async () => {
    setCookie("__Host-rev_csrf=token-123");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(200, []));

    await api.GET("/api/v1/years");
    await api.POST("/api/v1/auth/logout");

    const [get, post] = fetchMock.mock.calls.map((call) => call[0] as Request);
    expect(get!.headers.get("X-CSRF-Token")).toBeNull();
    expect(post!.headers.get("X-CSRF-Token")).toBe("token-123");
  });

  it("turns the error envelope into an ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json(409, {
        error: { code: "module_code_taken", message: "Taken.", request_id: "r1" },
      }),
    );

    const failure = await unwrap(api.GET("/api/v1/years")).catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 409, code: "module_code_taken", message: "Taken.", requestId: "r1" });
  });
});
