import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";

import { LoginPage } from "@/features/auth/LoginPage";
import { ChatPage } from "@/features/chat/ChatPage";
import { UsagePage } from "@/features/chat/UsagePage";
import { Dashboard } from "@/features/dashboard/Dashboard";
import { DocumentPage } from "@/features/documents/DocumentPage";
import { CalendarPage } from "@/features/planner/CalendarPage";
import { PlannerPage } from "@/features/planner/PlannerPage";
import { MistakesPage } from "@/features/learning/MistakesPage";
import { ProfilePage } from "@/features/learning/ProfilePage";
import { ReviewSession } from "@/features/learning/ReviewSession";
import { SearchPage } from "@/features/search/SearchPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { AttemptPage } from "@/features/study/AttemptPage";
import { DraftPage } from "@/features/study/DraftPage";
import { FlashcardsPage } from "@/features/study/FlashcardsPage";
import { MaterialPage } from "@/features/study/MaterialPage";
import { MaterialsPage } from "@/features/study/MaterialsPage";
import { QuestionBankPage } from "@/features/study/QuestionBankPage";
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

const materialsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/modules/$moduleId/materials",
  component: function MaterialsRouteView() {
    const { moduleId } = materialsRoute.useParams();
    return <MaterialsPage key={moduleId} moduleId={moduleId} />;
  },
});

const questionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/modules/$moduleId/questions",
  component: function QuestionsRouteView() {
    const { moduleId } = questionsRoute.useParams();
    return <QuestionBankPage key={moduleId} moduleId={moduleId} />;
  },
});

const flashcardsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/modules/$moduleId/flashcards",
  component: function FlashcardsRouteView() {
    const { moduleId } = flashcardsRoute.useParams();
    return <FlashcardsPage key={moduleId} moduleId={moduleId} />;
  },
});

const materialRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/materials/$materialId",
  component: function MaterialRouteView() {
    const { materialId } = materialRoute.useParams();
    return <MaterialPage key={materialId} materialId={materialId} />;
  },
});

const draftRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/drafts/$draftId",
  component: function DraftRouteView() {
    const { draftId } = draftRoute.useParams();
    return <DraftPage key={draftId} draftId={draftId} />;
  },
});

const attemptRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/attempts/$attemptId",
  component: function AttemptRouteView() {
    const { attemptId } = attemptRoute.useParams();
    return <AttemptPage key={attemptId} attemptId={attemptId} />;
  },
});

const moduleFilter = (search: Record<string, unknown>): { module_id?: string } =>
  typeof search.module_id === "string" ? { module_id: search.module_id } : {};

const reviewRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/review",
  validateSearch: moduleFilter,
  component: function ReviewRouteView() {
    const { module_id } = reviewRoute.useSearch();
    return (
      <div className="flex max-w-2xl flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Review flashcards</h1>
        <ReviewSession key={module_id ?? "all"} moduleId={module_id} />
      </div>
    );
  },
});

const mistakesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/mistakes",
  validateSearch: moduleFilter,
  component: function MistakesRouteView() {
    const { module_id } = mistakesRoute.useSearch();
    return <MistakesPage key={module_id ?? "all"} moduleId={module_id} />;
  },
});

const profileRoute = createRoute({ getParentRoute: () => appRoute, path: "/profile", component: ProfilePage });

const plannerRoute = createRoute({ getParentRoute: () => appRoute, path: "/planner", component: PlannerPage });

const calendarRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/calendar",
  component: function CalendarRouteView() {
    return <CalendarPage />;
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
    materialsRoute,
    questionsRoute,
    flashcardsRoute,
    materialRoute,
    draftRoute,
    attemptRoute,
    reviewRoute,
    mistakesRoute,
    profileRoute,
    plannerRoute,
    calendarRoute,
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
