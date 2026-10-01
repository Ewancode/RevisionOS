import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";

import { LoginPage } from "@/features/auth/LoginPage";
import { Dashboard } from "@/features/dashboard/Dashboard";
import { DocumentPage } from "@/features/documents/DocumentPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { ModulePage } from "@/features/structure/ModulePage";

import { AppShell } from "./AppShell";

const rootRoute = createRootRoute({ component: Outlet });

const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: LoginPage });

/** Signed-in layout; AppShell redirects to /login without a session. */
const appRoute = createRoute({ getParentRoute: () => rootRoute, id: "app", component: AppShell });

const dashboardRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: Dashboard });

const moduleRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/y/$yearId/m/$moduleId",
  component: function ModuleRouteView() {
    const { moduleId } = moduleRoute.useParams();
    // Keyed so local UI state resets when switching modules.
    return <ModulePage key={moduleId} moduleId={moduleId} />;
  },
});

const documentRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/doc/$documentId",
  component: function DocumentRouteView() {
    const { documentId } = documentRoute.useParams();
    return <DocumentPage key={documentId} documentId={documentId} />;
  },
});

const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: SettingsPage,
});

export const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([dashboardRoute, moduleRoute, documentRoute, settingsRoute]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
