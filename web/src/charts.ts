import * as Plot from "@observablehq/plot";
import type {
  Curve,
  Horizon,
  IndexAttribution,
  OilVsBei,
  Pca,
  SeriesPoint,
} from "./types";

const PURPLE = "#a78bfa";
const OIL = "#e0903a";
const BEIC = "#52b6a8";

const POS = "#e06c5a";
const NEG = "#4a90d9";
const LINE_COLORS = ["#d4a017", "#4a90d9", "#8b98a8"];

// Theme colors are read from CSS variables at render time, so charts re-rendered
// after a time-of-day theme change pick up the new ink/grid/muted automatically.
const cssVar = (name: string, fallback: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
  fallback;
const ink = () => cssVar("--ink", "#e6edf3");
const muted = () => cssVar("--muted", "#8b98a8");
const grid = () => cssVar("--grid", "#2a3543");

const base = () => ({
  background: "transparent",
  color: ink(),
  fontSize: "11px",
});

const gridStroke = () => ({ stroke: grid(), strokeOpacity: 0.5 });

/** Curve snapshot: yields at Current / 1W / 1M over evenly-spaced tenor ticks. */
export function curveSnapshot(curve: Curve): (HTMLElement | SVGSVGElement)[] {
  const tenorLabels = curve.tenors.map((t) => `${t}Y`);
  const points = curve.snapshots.flatMap((s) =>
    s.yields.map((y, i) => ({
      x: i,
      tenor: tenorLabels[i]!,
      yield: y,
      label: `${s.label} (${s.date})`,
    })),
  );
  const shift = curve.wow_shift_bp.map((v, i) => ({
    x: i,
    tenor: tenorLabels[i]!,
    bp: v,
  }));

  const lines = Plot.plot({
    style: base(),
    height: 260,
    marginLeft: 44,
    marginRight: 96,
    x: {
      domain: curve.tenors.map((_, i) => i),
      tickFormat: (i: number) => tenorLabels[i] ?? "",
      label: null,
      grid: true,
      ...gridStroke(),
    },
    y: { label: "Yield (%)", grid: true, ...gridStroke() },
    color: { domain: points.map((p) => p.label), range: LINE_COLORS, legend: true },
    marks: [
      Plot.line(points, { x: "x", y: "yield", stroke: "label", strokeWidth: 1.8 }),
      Plot.dot(points, { x: "x", y: "yield", fill: "label", r: 3 }),
    ],
  });

  const bars = Plot.plot({
    style: base(),
    height: 150,
    marginLeft: 44,
    marginRight: 96,
    x: {
      domain: curve.tenors.map((_, i) => i),
      tickFormat: (i: number) => tenorLabels[i] ?? "",
      label: "Tenor",
    },
    y: { label: "WoW Δ (bp)", grid: true, ...gridStroke() },
    marks: [
      Plot.barY(shift, {
        x: "x",
        y: "bp",
        fill: (d: { bp: number | null }) => ((d.bp ?? 0) >= 0 ? POS : NEG),
      }),
      Plot.ruleY([0], { stroke: ink(), strokeOpacity: 0.6 }),
    ],
  });

  return [lines, bars];
}

/** PCA loadings (level/slope/curvature) and the rich/cheap residual bars. */
export function pcaCharts(pca: Pca): (HTMLElement | SVGSVGElement)[] {
  const loadingsLong = pca.loadings.flatMap((row) =>
    ["PC1", "PC2", "PC3"].map((pc) => ({
      tenor: String(row.tenor),
      pc,
      value: row[pc] as number | null,
    })),
  );
  const loadings = Plot.plot({
    style: base(),
    height: 240,
    marginLeft: 44,
    x: { label: "Tenor", domain: pca.loadings.map((r) => String(r.tenor)) },
    y: { label: "Loading", grid: true, ...gridStroke() },
    color: { domain: ["PC1", "PC2", "PC3"], range: LINE_COLORS, legend: true },
    marks: [
      Plot.line(loadingsLong, {
        x: "tenor",
        y: "value",
        stroke: "pc",
        strokeWidth: 1.8,
      }),
      Plot.dot(loadingsLong, { x: "tenor", y: "value", fill: "pc", r: 3 }),
      Plot.ruleY([0], { stroke: muted(), strokeOpacity: 0.5 }),
    ],
  });

  const rich = Plot.plot({
    style: base(),
    height: 240,
    marginLeft: 44,
    x: { label: "Tenor", domain: pca.rich_cheap.map((r) => r.tenor) },
    y: { label: "Residual (bp, + = cheap)", grid: true, ...gridStroke() },
    marks: [
      Plot.barY(pca.rich_cheap, {
        x: "tenor",
        y: "bp",
        fill: (d: { bp: number | null }) => ((d.bp ?? 0) >= 0 ? POS : NEG),
      }),
      Plot.ruleY([0], { stroke: ink(), strokeOpacity: 0.6 }),
    ],
  });

  return [loadings, rich];
}

const parsed = (s: SeriesPoint[]) =>
  s
    .filter((p) => p.value !== null)
    .map((p) => ({ date: new Date(p.date), value: p.value as number }));

/** USD/JPY (left) against the US–JP 10Y differential (right), dual-axis feel. */
export function usdjpyVsDifferential(
  usdjpy: SeriesPoint[],
  fitted: SeriesPoint[],
): HTMLElement | SVGSVGElement {
  const px = parsed(usdjpy);
  const fit = parsed(fitted);
  return Plot.plot({
    style: base(),
    height: 300,
    marginLeft: 50,
    marginRight: 20,
    x: { label: null, grid: true, ...gridStroke() },
    y: { label: "USD/JPY", grid: true, ...gridStroke() },
    color: {
      domain: ["USD/JPY", "Rate-implied fair value"],
      range: [ink(), "#d4a017"],
      legend: true,
    },
    marks: [
      Plot.line(px, { x: "date", y: "value", stroke: () => "USD/JPY", strokeWidth: 1.5 }),
      Plot.line(fit, {
        x: "date",
        y: "value",
        stroke: () => "Rate-implied fair value",
        strokeWidth: 1.4,
        strokeDasharray: "4 3",
      }),
    ],
  });
}

export interface BflyStats {
  mu: number;
  sd: number;
  last: number;
  z: number;
  n: number;
}

/** Mean / population-σ / latest level & z over a fly's spread series. */
export function bflyStats(points: SeriesPoint[]): BflyStats | null {
  const v = points
    .map((p) => p.value)
    .filter((x): x is number => x !== null);
  if (v.length === 0) return null;
  const mu = v.reduce((a, b) => a + b, 0) / v.length;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - mu) ** 2, 0) / v.length);
  const last = v[v.length - 1]!;
  return { mu, sd, last, z: sd ? (last - mu) / sd : 0, n: v.length };
}

/** One butterfly panel: spread (bp) line with mean + ±1σ/±2σ bands. */
export function butterflyPanel(
  points: SeriesPoint[],
  stats: BflyStats,
): HTMLElement | SVGSVGElement {
  const line = points
    .filter((p) => p.value !== null)
    .map((p) => ({ date: new Date(p.date), value: p.value as number }));
  const x1 = line[0]!.date;
  const x2 = line[line.length - 1]!.date;
  const { mu, sd } = stats;
  const band = (k: number, opacity: number) =>
    Plot.rect([{}], {
      x1,
      x2,
      y1: mu - k * sd,
      y2: mu + k * sd,
      fill: PURPLE,
      fillOpacity: opacity,
    });

  return Plot.plot({
    style: base(),
    height: 150,
    marginLeft: 40,
    marginRight: 12,
    x: { label: null, grid: true, ...gridStroke() },
    y: { label: "bp", grid: true, ...gridStroke() },
    marks: [
      band(2, 0.1),
      band(1, 0.18),
      Plot.ruleY([mu], { stroke: ink(), strokeDasharray: "3 3", strokeOpacity: 0.6 }),
      Plot.line(line, { x: "date", y: "value", stroke: PURPLE, strokeWidth: 1.4 }),
    ],
  });
}

/** Index price transition: a simple level line over the available history. */
export function priceTransition(
  points: SeriesPoint[],
  color = "#5aa9e6",
): HTMLElement | SVGSVGElement {
  const line = points
    .filter((p) => p.value !== null)
    .map((p) => ({ date: new Date(p.date), value: p.value as number }));
  return Plot.plot({
    style: base(),
    height: 200,
    marginLeft: 56,
    marginRight: 16,
    x: { label: null, grid: true, ...gridStroke() },
    y: { label: "Index level", grid: true, ...gridStroke() },
    marks: [
      Plot.areaY(line, { x: "date", y: "value", fill: color, fillOpacity: 0.08 }),
      Plot.line(line, { x: "date", y: "value", stroke: color, strokeWidth: 1.5 }),
    ],
  });
}

/** Sector contribution (weight x return, pp) to an index move, sorted desc. */
export function sectorContribution(
  attr: IndexAttribution,
  horizon: Horizon,
): HTMLElement | SVGSVGElement {
  const cKey = horizon === "wow" ? "contrib_wow" : "contrib_1m";
  const rows = attr.sectors
    .map((s) => ({ sector: s.sector, contrib: s[cKey] }))
    .filter((s) => s.contrib !== null) as { sector: string; contrib: number }[];
  rows.sort((a, b) => b.contrib - a.contrib);

  return Plot.plot({
    style: base(),
    height: 26 * rows.length + 44,
    marginLeft: 188,
    marginRight: 44,
    x: { label: "Contribution to index move (pp)", grid: true, ...gridStroke() },
    y: { label: null, domain: rows.map((r) => r.sector) },
    marks: [
      Plot.barX(rows, {
        y: "sector",
        x: "contrib",
        fill: (d: { contrib: number }) => (d.contrib >= 0 ? POS : NEG),
      }),
      Plot.text(
        rows.filter((d) => d.contrib >= 0),
        {
          y: "sector",
          x: "contrib",
          text: (d: { contrib: number }) => "+" + d.contrib.toFixed(2),
          textAnchor: "start",
          dx: 4,
          fill: ink(),
          fontSize: 10,
        },
      ),
      Plot.text(
        rows.filter((d) => d.contrib < 0),
        {
          y: "sector",
          x: "contrib",
          text: (d: { contrib: number }) => d.contrib.toFixed(2),
          textAnchor: "end",
          dx: -4,
          fill: ink(),
          fontSize: 10,
        },
      ),
      Plot.ruleX([0], { stroke: ink(), strokeOpacity: 0.6 }),
    ],
  });
}

/** WTI crude (left axis) vs 10Y breakeven (right axis), dual-scale overlay. */
export function oilVsBei(d: OilVsBei): HTMLElement | SVGSVGElement {
  const wti = parsed(d.wti);
  const bei = parsed(d.bei);
  const wv = wti.map((p) => p.value);
  const bv = bei.map((p) => p.value);
  const wMin = Math.min(...wv);
  const wMax = Math.max(...wv);
  const bMin = Math.min(...bv);
  const bMax = Math.max(...bv);
  const padW = (wMax - wMin) * 0.05 || 1;
  const padB = (bMax - bMin) * 0.05 || 0.1;
  const w0 = wMin - padW;
  const w1 = wMax + padW;
  const b0 = bMin - padB;
  const b1 = bMax + padB;
  // Map breakeven (%) onto the WTI ($) axis so both share one y scale.
  const scale = (b: number) => w0 + ((b - b0) / (b1 - b0)) * (w1 - w0);
  const inv = (y: number) => b0 + ((y - w0) / (w1 - w0)) * (b1 - b0);
  const beiScaled = bei.map((p) => ({ date: p.date, value: scale(p.value) }));
  const rightTicks = Array.from({ length: 5 }, (_, i) => w0 + (i / 4) * (w1 - w0));

  return Plot.plot({
    style: base(),
    height: 300,
    marginLeft: 52,
    marginRight: 56,
    x: { label: null, grid: true, ...gridStroke() },
    y: { domain: [w0, w1], label: "WTI ($/bbl)", grid: true, ...gridStroke() },
    color: {
      domain: ["WTI crude ($/bbl)", "10Y breakeven (%)"],
      range: [OIL, BEIC],
      legend: true,
    },
    marks: [
      Plot.line(wti, {
        x: "date",
        y: "value",
        stroke: () => "WTI crude ($/bbl)",
        strokeWidth: 1.5,
      }),
      Plot.line(beiScaled, {
        x: "date",
        y: "value",
        stroke: () => "10Y breakeven (%)",
        strokeWidth: 1.5,
      }),
      Plot.axisY(rightTicks, {
        anchor: "right",
        label: "10Y breakeven (%)",
        tickFormat: (y: number) => inv(y).toFixed(2),
        color: BEIC,
      }),
    ],
  });
}

/** Horizontal z-score bar chart for the cross-asset momentum heat row. */
export function zscoreBars(
  data: { asset: string; z: number | null }[],
): HTMLElement | SVGSVGElement {
  const rows = data.filter((d) => d.z !== null);
  return Plot.plot({
    style: base(),
    height: 26 * rows.length + 40,
    marginLeft: 78,
    marginRight: 30,
    x: { label: "1W z-score", domain: [-3, 3], grid: true, ...gridStroke() },
    y: { label: null, domain: rows.map((r) => r.asset) },
    marks: [
      Plot.barX(rows, {
        y: "asset",
        x: "z",
        fill: (d: { z: number | null }) => ((d.z ?? 0) >= 0 ? POS : NEG),
      }),
      Plot.ruleX([0], { stroke: ink(), strokeOpacity: 0.6 }),
    ],
  });
}
