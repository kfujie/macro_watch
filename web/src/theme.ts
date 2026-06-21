// Time-of-day theme: the page interpolates between a dark palette (midnight) and
// a light palette (noon). At local noon the background is white; at midnight it
// is the original dark. The factor follows a cosine of the hour so the change is
// smooth, peaking at 12:00 and bottoming at 00:00.

interface Palette {
  bg: string;
  panel: string;
  border: string;
  grid: string;
  ink: string;
  muted: string;
  accent: string;
}

const DARK: Palette = {
  bg: "#0f1419",
  panel: "#1a212b",
  border: "#2a3543",
  grid: "#2a3543",
  ink: "#e6edf3",
  muted: "#8b98a8",
  accent: "#d4a017",
};

const LIGHT: Palette = {
  bg: "#ffffff",
  panel: "#f4f6f9",
  border: "#dbe1e8",
  grid: "#dbe1e8",
  ink: "#1b232c",
  muted: "#5b6776",
  accent: "#b07d0a",
};

const hex = (c: string): [number, number, number] => {
  const n = parseInt(c.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

const toHex = (rgb: [number, number, number]): string =>
  "#" +
  rgb
    .map((v) => Math.round(v).toString(16).padStart(2, "0"))
    .join("");

const lerp = (a: string, b: string, t: number): string => {
  const [ar, ag, ab] = hex(a);
  const [br, bg, bb] = hex(b);
  return toHex([ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t]);
};

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

/** Daylight factor in [0,1]: 1 at local noon, 0 at local midnight (cosine). */
export function daylightFactor(now: Date): number {
  const hours = now.getHours() + now.getMinutes() / 60;
  return (1 - Math.cos((hours / 24) * 2 * Math.PI)) / 2;
}

/**
 * Apply the time-of-day palette to the document root.
 *
 * Surface colors (bg/panel/border/grid/accent) wash continuously between dark
 * and light. **Foreground** colors (ink/muted) instead snap to whichever extreme
 * reads against the background, so text never collapses to low contrast at the
 * dawn/dusk midpoint (where a naive lerp would make text and background both grey).
 */
export function applyTimeTheme(now: Date): number {
  const t = daylightFactor(now);
  const lightUI = t >= 0.5;
  // Surfaces skip the dead-neutral middle (wash 0.42–0.58): the background is
  // always clearly on the dark or light side, so the accent and red/blue values
  // never wash out into grey. Still hits white at noon (t=1) and dark at midnight.
  const wash = lightUI
    ? 0.58 + ((t - 0.5) / 0.5) * 0.42
    : clamp01((t / 0.5) * 0.42);
  const fg = lightUI ? LIGHT : DARK;
  const root = document.documentElement;

  const surfaces: (keyof Palette)[] = ["bg", "panel", "border", "grid", "accent"];
  surfaces.forEach((k) => root.style.setProperty(`--${k}`, lerp(DARK[k], LIGHT[k], wash)));
  root.style.setProperty("--ink", fg.ink);
  root.style.setProperty("--muted", fg.muted);
  root.style.setProperty("color-scheme", lightUI ? "light" : "dark");
  return t;
}
