import { SystemStatus } from "@/features/system/SystemStatus";

export function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Revision OS</h1>
        <p className="text-muted">Scaffold — features arrive from Phase 2.</p>
      </header>
      <SystemStatus />
    </main>
  );
}
