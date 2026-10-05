/// <reference types="node" />  // these tests read files from disk
/**
 * The service worker (public/sw.js), run against a fake worker scope: it
 * shows each pushed reminder, opens the right page when one is tapped, and
 * only ever touches page loads, never API requests.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it, vi } from "vitest";

const SOURCE = readFileSync(`${process.cwd()}/public/sw.js`, "utf8");

type Listener = (event: Record<string, unknown>) => void;

function load() {
  const listeners: Record<string, Listener> = {};
  const showNotification = vi.fn(() => Promise.resolve());
  const focus = vi.fn(() => Promise.resolve());
  const navigate = vi.fn(() => Promise.resolve());
  const openWindow = vi.fn(() => Promise.resolve());
  const windows: { url: string; focus: typeof focus; navigate: typeof navigate }[] = [];
  const scope = {
    addEventListener: (type: string, fn: Listener) => {
      listeners[type] = fn;
    },
    registration: { showNotification },
    location: { origin: "https://revision.example" },
    clients: { matchAll: () => Promise.resolve(windows), openWindow, claim: () => Promise.resolve() },
    skipWaiting: vi.fn(),
  };
  const caches = { open: () => Promise.resolve({ addAll: () => Promise.resolve() }), keys: () => Promise.resolve([]), match: vi.fn() };
  new Function("self", "caches", "fetch", SOURCE)(scope, caches, vi.fn(() => Promise.reject(new Error("offline"))));
  const fire = async (type: string, event: Record<string, unknown>) => {
    let waited: Promise<unknown> | undefined;
    listeners[type]!({ ...event, waitUntil: (p: Promise<unknown>) => (waited = p), respondWith: (p: Promise<unknown>) => (waited = p) });
    await waited;
  };
  return { listeners, fire, showNotification, openWindow, windows, focus, navigate, caches };
}

describe("the service worker", () => {
  it("shows a pushed reminder with its title, body and page", async () => {
    const sw = load();
    const data = { title: "Your MATH101 exam is in 7 days.", body: "Final, Mon 12 Oct", url: "/planner", tag: "revision-os-exam" };
    await sw.fire("push", { data: { json: () => data, text: () => JSON.stringify(data) } });
    expect(sw.showNotification).toHaveBeenCalledWith("Your MATH101 exam is in 7 days.", {
      body: "Final, Mon 12 Oct",
      tag: "revision-os-exam",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: "/planner" },
    });
  });

  it("opens the reminder's page when tapped, reusing an open window", async () => {
    const sw = load();
    const close = vi.fn();
    await sw.fire("notificationclick", { notification: { close, data: { url: "/review" } } });
    expect(close).toHaveBeenCalled();
    expect(sw.openWindow).toHaveBeenCalledWith("https://revision.example/review");

    sw.windows.push({ url: "https://revision.example/", focus: sw.focus, navigate: sw.navigate });
    await sw.fire("notificationclick", { notification: { close, data: { url: "/planner" } } });
    expect(sw.focus).toHaveBeenCalled();
    expect(sw.navigate).toHaveBeenCalledWith("https://revision.example/planner");

    // A link to another site opens the app instead.
    await sw.fire("notificationclick", { notification: { close, data: { url: "https://evil.example/x" } } });
    expect(sw.navigate).toHaveBeenLastCalledWith("https://revision.example/");
  });

  it("handles page loads only, with the offline page as fallback", async () => {
    const sw = load();
    let responded = false;
    sw.listeners.fetch!({ request: { mode: "cors", url: "/api/v1/plan" }, respondWith: () => (responded = true) });
    expect(responded).toBe(false); // API requests go straight to the network
    await sw.fire("fetch", { request: { mode: "navigate", url: "/planner" } });
    expect(sw.caches.match).toHaveBeenCalledWith("/offline.html");
  });
});
