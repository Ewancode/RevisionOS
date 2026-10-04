import { useCallback, useState } from "react";

import { useCodingConfig } from "./queries";
import { runnerFor, type Language } from "./runtime";
import type { RunRequest, RunResult } from "./runtime/types";

const warmed = new Set<Language>();

/** Run code in the browser with the configured runtime for a language. */
export function useRunner(language: Language) {
  const config = useCodingConfig();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);

  const run = useCallback(
    async (request: RunRequest): Promise<RunResult | null> => {
      const c = config.data;
      const runtime = c?.runtimes[language];
      if (!c || !runtime) return null;
      setRunning(true);
      try {
        const runner = runnerFor(language, {
          baseUrl: runtime.base_url,
          timeoutMs: c.run_timeout_seconds * 1000,
          firstRunTimeoutMs: c.first_run_timeout_seconds * 1000,
          maxOutputChars: c.max_output_chars,
        });
        const outcome = await runner.run(request);
        warmed.add(language);
        setResult(outcome);
        return outcome;
      } finally {
        setRunning(false);
      }
    },
    [config.data, language],
  );

  const label = config.data?.runtimes[language]?.label ?? (language === "python" ? "Python" : "R");
  return {
    run,
    running,
    result,
    setResult,
    ready: Boolean(config.data),
    configError: config.error,
    status: running
      ? warmed.has(language)
        ? "Running…"
        : `Starting ${label} in your browser (the first time downloads it, which can take a minute)…`
      : null,
  };
}
