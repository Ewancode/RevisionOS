import { describe, expect, it } from "vitest";

import { greeting } from "./greeting";
import { applyAppearance, cachedAppearance } from "./theme";

describe("appearance", () => {
  it("forces a theme, or defers to the system", () => {
    const root = document.documentElement;
    applyAppearance({ theme: "dark", accent_colour: "#0ea5e9" });
    expect(root.dataset.theme).toBe("dark");
    expect(root.style.getPropertyValue("--color-accent")).toBe("#0ea5e9");

    applyAppearance({ theme: "system", accent_colour: "#0ea5e9" });
    expect(root.dataset.theme).toBeUndefined();
  });

  it("remembers the last appearance for the next page load", () => {
    applyAppearance({ theme: "light", accent_colour: "#123456" });
    expect(cachedAppearance()).toEqual({ theme: "light", accent_colour: "#123456" });
  });
});

describe("greeting", () => {
  it.each([
    [9, "Good morning"],
    [14, "Good afternoon"],
    [20, "Good evening"],
  ])("at %i:00 says %s", (hour, expected) => {
    expect(greeting(new Date(2026, 9, 1, hour))).toBe(expected);
  });
});
