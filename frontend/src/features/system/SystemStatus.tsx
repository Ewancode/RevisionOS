import { useReadiness } from "./useReadiness";

const LABELS: Record<string, string> = { database: "Database", redis: "Job queue" };

export function SystemStatus() {
  const { data, isPending, isError } = useReadiness();

  if (isPending) {
    return <p className="text-muted">Checking services…</p>;
  }
  if (isError) {
    return (
      <p role="alert" className="text-danger">
        Cannot reach the API. Is the backend running?
      </p>
    );
  }

  return (
    <section aria-labelledby="status-heading">
      <h2 id="status-heading" className="mb-2 text-sm font-medium text-muted">
        System status: {data.status === "ready" ? "all services ready" : "degraded"}
      </h2>
      <ul className="space-y-1">
        {Object.entries(data.checks).map(([name, state]) => (
          <li key={name} className="flex justify-between gap-8">
            <span>{LABELS[name] ?? name}</span>
            <span className={state === "ok" ? "text-success" : "text-danger"}>
              {state === "ok" ? "OK" : "Unavailable"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
