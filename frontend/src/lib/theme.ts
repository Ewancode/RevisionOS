/**
 * Light / dark / system theme and the accent colour (ARCHITECTURE.md §3).
 * The choice is stored server-side in user_settings; a localStorage copy lets
 * the next page load paint in the right theme before the session request
 * returns.
 */

import { readableAccent, textOn } from "./contrast";

export type Theme = "light" | "dark" | "system";

// The darkest light and lightest dark backgrounds text sits on (index.css).
const LIGHT_BG = "#f7f7f8";
const DARK_SURFACE = "#1b1b1f";

const STORAGE_KEY = "revision-os:appearance";
export const DEFAULT_ACCENT = "#4f46e5";

export interface Appearance {
  theme: Theme;
  accent_colour: string;
}

export function applyAppearance({ theme, accent_colour }: Appearance, root = document.documentElement) {
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  root.style.setProperty("--color-accent", accent_colour);
  // Keep text on and in the accent readable, whatever colour you chose.
  root.style.setProperty("--color-on-accent", textOn(accent_colour));
  root.style.setProperty("--accent-on-light", readableAccent(accent_colour, LIGHT_BG));
  root.style.setProperty("--accent-on-dark", readableAccent(accent_colour, DARK_SURFACE));
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, accent_colour }));
  } catch {
    // Storage can be unavailable (private mode); the server copy is canonical.
  }
}

export function cachedAppearance(): Appearance | undefined {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Appearance) : undefined;
  } catch {
    return undefined;
  }
}
