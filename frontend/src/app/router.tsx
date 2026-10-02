import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";

import { LoginPage } from "@/features/auth/LoginPage";
import { ChatPage } from "@/features/chat/ChatPage";
import { UsagePage } from "@/features/chat/UsagePage";
import { Dashboard } from "@/features/dashboard/Dashboard";
import { DocumentPage } from "@/features/documents/DocumentPage";
import { SearchPage } from "@/features/search/SearchPage";
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
  // ?page=n opens the document at that page (search results and citations).
  validateSearch: (search: Record<string, unknown>): { page?: number } => {
    const page = Number(search.page);
    return Number.isInteger(page) && page > 0 ? { page } : {};
  },
  component: function DocumentRouteView() {
    const { documentId } = documentRoute.useParams();
    const { page } = documentRoute.useSearch();
    return <DocumentPage key={documentId} documentId={documentId} focusPage={page} />;
  },
});

const searchRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/search",
  validateSearch: (search: Record<string, unknown>): { q: string; module_id?: string } => ({
    q: typeof search.q === "string" ? search.q : "",
    ...(typeof search.module_id === "string" ? { module_id: search.module_id } : {}),
  }),
  component: function SearchRouteView() {
    const { q, module_id } = searchRoute.useSearch();
    return <SearchPage key={module_id ?? "all"} q={q} moduleId={module_id} />;
  },
});

const chatRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/chat",
  // ?module_id= starts the conversation from a module (searches start there).
  validateSearch: (search: Record<string, unknown>): { module_id?: string } =>
    typeof search.module_id === "string" ? { module_id: search.module_id } : {},
  component: function NewChatRouteView() {
    const { module_id } = chatRoute.useSearch();
    return <ChatPage moduleId={module_id} />;
  },
});

const conversationRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/chat/$conversationId",
  component: function ConversationRouteView() {
    const { conversationId } = conversationRoute.useParams();
    return <ChatPage conversationId={conversationId} />;
  },
});

const usageRoute = createRoute({ getParentRoute: () => appRoute, path: "/usage", component: UsagePage });

const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: SettingsPage,
});

export const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([
    dashboardRoute,
    moduleRoute,
    documentRoute,
    searchRoute,
    chatRoute,
    conversationRoute,
    usageRoute,
    settingsRoute,
  ]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
