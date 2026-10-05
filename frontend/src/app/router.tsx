import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type ErrorComponentProps,
} from "@tanstack/react-router";

import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { CodingPage } from "@/features/coding/CodingPage";
import { ExercisePage } from "@/features/coding/ExercisePage";
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

/** If a page crashes: say so, and offer a way back, never a blank screen. */
function CrashPage({ error, reset }: ErrorComponentProps) {
  return (
    <main className="mx-auto flex max-w-lg flex-col gap-3 p-6">
      <h1 className="text-xl font-semibold">Something went wrong on this page</h1>
      <p className="text-sm text-muted">
        Your work is saved on the server. Try again, or go back to Today.
      </p>
      <pre className="overflow-x-auto rounded-md bg-surface p-2 text-xs text-muted">{error instanceof Error ? error.message : String(error)}</pre>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => {
            reset();
            window.location.reload();
          }}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent"
        >
          Try again
        </button>
        <a href="/" className="rounded-md border border-border px-3 py-1.5 text-sm font-medium">
          Go to Today
        </a>
      </div>
    </main>
  );
}

const rootRoute = createRootRoute({ component: Outlet, errorComponent: CrashPage });

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

const codingRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/modules/$moduleId/coding",
  component: function CodingRouteView() {
    const { moduleId } = codingRoute.useParams();
    return <CodingPage key={moduleId} moduleId={moduleId} />;
  },
});

const exerciseRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/coding/$exerciseId",
  component: function ExerciseRouteView() {
    const { exerciseId } = exerciseRoute.useParams();
    return <ExercisePage key={exerciseId} exerciseId={exerciseId} />;
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

const analyticsRoute = createRoute({ getParentRoute: () => appRoute, path: "/analytics", component: AnalyticsPage });

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
    codingRoute,
    exerciseRoute,
    materialRoute,
    draftRoute,
    attemptRoute,
    reviewRoute,
    mistakesRoute,
    profileRoute,
    plannerRoute,
    calendarRoute,
    analyticsRoute,
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
