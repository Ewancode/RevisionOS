import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeApi, UNAUTHORISED } from "@/test/fakeApi";

import { routeTree } from "./router";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1",
  academic_year_id: "y1",
  code: "MATH103",
  title: "Linear Algebra",
  subject_tag: "Mathematics",
  credits: 15,
  colour: "#4f46e5",
  status: "active",
};

function renderApp(path: string) {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("app", () => {
  it("sends signed-out visitors to the login page, then into the dashboard", async () => {
    let signedIn = false;
    const { calls } = fakeApi({
      "GET /api/v1/auth/session": () => (signedIn ? [200, session] : UNAUTHORISED),
      "POST /api/v1/auth/login": (_req, body) => {
        const { password } = body as { password: string };
        if (password !== "correct horse") {
          return [401, { error: { code: "invalid_credentials", message: "Not recognised.", request_id: "t" } }];
        }
        signedIn = true;
        return [200, session];
      },
      "GET /api/v1/years": () => [200, [year]],
      "GET /api/v1/modules": () => [200, [module]],
    });
    const user = userEvent.setup();
    const router = renderApp("/");

    await screen.findByRole("heading", { name: /sign in to revision os/i });
    expect(router.state.location.pathname).toBe("/login");

    await user.type(screen.getByLabelText("Email"), "ewan@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not recognised.");
    expect(screen.getByLabelText("Password")).toHaveValue(""); // cleared after a failure

    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: /, Ewan$/ })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(await within(nav).findByRole("link", { name: /MATH103 Linear Algebra/ })).toBeInTheDocument();
    expect(within(nav).getByText("Mathematics")).toBeInTheDocument(); // grouped by subject
    expect(calls.filter((c) => c.path === "/api/v1/auth/login").at(-1)?.body).toEqual({
      email: "ewan@example.com",
      password: "correct horse",
    });
  });

  it("only deletes a module after explicit confirmation", async () => {
    const { calls } = fakeApi({
      "GET /api/v1/auth/session": () => [200, session],
      "GET /api/v1/years": () => [200, [year]],
      "GET /api/v1/modules": () => [200, [module]],
      "GET /api/v1/modules/m1": () => [200, module],
      "GET /api/v1/modules/m1/topics": () => [200, []],
      "DELETE /api/v1/modules/m1": () => [204, null],
    });
    const user = userEvent.setup();
    const router = renderApp("/y/y1/m/m1");

    await screen.findByRole("heading", { name: "Linear Algebra" });
    const deletes = () => calls.filter((c) => c.method === "DELETE");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: /delete math103 linear algebra/i });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(deletes()).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const again = await screen.findByRole("dialog");
    await user.click(within(again).getByRole("button", { name: "Delete" }));

    await screen.findByRole("heading", { name: /, Ewan$/ });
    expect(deletes()).toEqual([{ method: "DELETE", path: "/api/v1/modules/m1", body: undefined }]);
    expect(router.state.location.pathname).toBe("/");
  });
});
