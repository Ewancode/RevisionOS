/// <reference types="node" />  // these tests read files from disk
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";

import { AA, contrast, readableAccent, textOn } from "./contrast";

// The stylesheet itself (Vitest returns CSS imports empty).
const CSS = readFileSync(`${process.cwd()}/src/index.css`, "utf8");

/** The colour tokens of a CSS block, from index.css itself. */
function tokens(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1]!, m[2]!]));
}

const light = tokens(CSS.slice(CSS.indexOf(":root {"), CSS.indexOf("}", CSS.indexOf(":root {"))));
const darkStart = CSS.indexOf(':root[data-theme="dark"]');
const dark = { ...light, ...tokens(CSS.slice(darkStart, CSS.indexOf("}", darkStart))) };

// [text, background]: every way the app puts text on a colour.
const PAIRS: [string, string][] = [
  ["color-fg", "color-bg"],
  ["color-fg", "color-surface"],
  ["color-muted", "color-bg"],
  ["color-muted", "color-surface"],
  ["color-danger", "color-bg"],
  ["color-danger", "color-surface"],
  ["color-success", "color-bg"],
  ["color-success", "color-surface"],
  ["color-on-accent", "color-accent"],
  ["color-on-danger", "color-danger"],
];

describe("colour contrast (WCAG AA, 4.5:1 for text)", () => {
  for (const [name, theme, accentText] of [
    ["light", light, light["accent-on-light"]],
    ["dark", dark, light["accent-on-dark"]],
  ] as const) {
    it(`holds for every text colour in the ${name} theme`, () => {
      for (const [fg, bg] of PAIRS) {
        expect(theme[fg], fg).toBeDefined();
        expect(contrast(theme[fg]!, theme[bg]!), `${fg} on ${bg} (${name})`).toBeGreaterThanOrEqual(AA);
      }
      for (const bg of ["color-bg", "color-surface"]) {
        expect(contrast(accentText!, theme[bg]!), `accent text on ${bg} (${name})`).toBeGreaterThanOrEqual(AA);
      }
    });
  }

  it("keeps any accent you choose readable", () => {
    for (const accent of ["#4f46e5", "#ffeb3b", "#00bcd4", "#111111", "#e91e63", "#8bc34a"]) {
      expect(contrast(textOn(accent), accent), accent).toBeGreaterThanOrEqual(AA);
      for (const background of [light["color-bg"]!, light["color-surface"]!, dark["color-bg"]!, dark["color-surface"]!]) {
        expect(contrast(readableAccent(accent, background), background), `${accent} on ${background}`).toBeGreaterThanOrEqual(AA);
      }
    }
    // An accent that already reads well is left alone.
    expect(readableAccent("#4f46e5", "#ffffff")).toBe("#4f46e5");
  });
});
