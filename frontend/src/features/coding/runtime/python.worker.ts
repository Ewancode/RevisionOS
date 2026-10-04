/**
 * Python in a Web Worker, with Pyodide loaded from its pinned CDN URL.
 * Your code never leaves the browser. The harness (harness.py, also run by
 * the backend's tests under CPython) runs your code and then each test.
 */
import HARNESS from "./harness.py?raw";

/** Pyodide's package-loading chatter stays out of your program's output. */
interface Quiet {
  messageCallback: (message: string) => void;
  errorCallback: (message: string) => void;
}

const quiet: Quiet = { messageCallback: () => undefined, errorCallback: () => undefined };

interface Pyodide {
  globals: { set(name: string, value: unknown): void };
  setStdout(options: { batched: (text: string) => void }): void;
  setStderr(options: { batched: (text: string) => void }): void;
  loadPackagesFromImports(code: string, options?: Quiet): Promise<unknown>;
  loadPackage(names: string[], options?: Quiet): Promise<unknown>;
  runPythonAsync(code: string): Promise<unknown>;
}

type Incoming =
  | { type: "init"; baseUrl: string }
  | { type: "run"; id: number; code: string; tests: { name: string; code: string }[]; mode: string; packages: string[] };

const scope = self as unknown as {
  postMessage(message: unknown): void;
  onmessage: ((event: MessageEvent<Incoming>) => void) | null;
};

let pyodide: Promise<Pyodide> | null = null;

async function load(baseUrl: string): Promise<Pyodide> {
  const module = (await import(/* @vite-ignore */ `${baseUrl}pyodide.mjs`)) as {
    loadPyodide(options: { indexURL: string }): Promise<Pyodide>;
  };
  return module.loadPyodide({ indexURL: baseUrl });
}

scope.onmessage = async (event) => {
  const message = event.data;
  if (message.type === "init") {
    pyodide ??= load(message.baseUrl);
    try {
      await pyodide;
      scope.postMessage({ type: "ready" });
    } catch (error) {
      pyodide = null;
      scope.postMessage({ type: "failed", error: String(error) });
    }
    return;
  }
  if (!pyodide) {
    scope.postMessage({ type: "result", id: message.id, failure: "Python is not loaded." });
    return;
  }
  const py = await pyodide;
  const output: string[] = [];
  py.setStdout({ batched: (text) => output.push(text) });
  py.setStderr({ batched: (text) => output.push(text) });
  const started = performance.now();
  try {
    if (message.packages.length) {
      await py.loadPackage(message.packages, quiet).catch((e: unknown) => output.push(`Could not load packages: ${String(e)}`));
    }
    await py.loadPackagesFromImports(message.code + "\n" + message.tests.map((t) => t.code).join("\n"), quiet);
    // Packages are in: from here on the run's time limit applies.
    scope.postMessage({ type: "started", id: message.id });
    py.globals.set("__user_code", message.code);
    py.globals.set("__tests_json", JSON.stringify(message.tests));
    py.globals.set("__mode", message.mode);
    const json = (await py.runPythonAsync(HARNESS)) as string;
    scope.postMessage({
      type: "result",
      id: message.id,
      output: output.join("\n"),
      result: JSON.parse(json) as unknown,
      runtimeMs: Math.round(performance.now() - started),
    });
  } catch (error) {
    scope.postMessage({ type: "result", id: message.id, failure: String(error), output: output.join("\n") });
  }
};
