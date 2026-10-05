/** WCAG contrast, so a custom accent colour stays readable (SPEC 63). */

export const AA = 4.5;

function channels(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

function toHex(rgb: [number, number, number]): string {
  return `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
}

export function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p) as [number, number];
  return (x + 0.05) / (y + 0.05);
}

function mix(a: string, b: string, t: number): string {
  const [p, q] = [channels(a), channels(b)];
  return toHex([0, 1, 2].map((i) => p[i]! + (q[i]! - p[i]!) * t) as [number, number, number]);
}

/** Text on an accent-coloured button: white or black, whichever reads better.
 *  One of the two always reaches 4.58:1, whatever the colour. */
export function textOn(background: string): string {
  return contrast("#ffffff", background) >= contrast("#000000", background) ? "#ffffff" : "#000000";
}

/**
 * The accent as text on a background: the accent itself if it already
 * meets AA, otherwise moved towards white (dark backgrounds) or black
 * (light ones) just far enough to.
 */
export function readableAccent(accent: string, background: string): string {
  const towards = luminance(background) < 0.5 ? "#ffffff" : "#000000";
  for (let t = 0; t <= 1.0001; t += 0.05) {
    const candidate = mix(accent, towards, t);
    if (contrast(candidate, background) >= AA) return candidate;
  }
  return towards;
}
