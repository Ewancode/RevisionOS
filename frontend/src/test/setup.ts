import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no layout; the router's scroll restoration calls this on navigation.
window.scrollTo = () => {};

// The code editor (CodeMirror) measures text; jsdom has no layout, so
// measurements are empty.
const noRects = () => Object.assign([], { item: () => null }) as unknown as DOMRectList;
Range.prototype.getClientRects = noRects;
Range.prototype.getBoundingClientRect = () => new DOMRect();

// jsdom has no ResizeObserver or scrollIntoView (the command palette uses both).
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= () => {};

afterEach(() => {
  cleanup();
  localStorage.clear();
});
