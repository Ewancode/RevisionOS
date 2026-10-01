/**
 * Light / dark / system theme and the accent colour (ARCHITECTURE.md §3).
 * The choice is stored server-side in user_settings; a localStorage copy lets
 * the next page load paint in the right theme before the session request
 * returns.
 */

export type Theme = "light" | "dark" | "system";

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
