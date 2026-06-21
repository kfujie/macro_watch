import * as Plot from "@observablehq/plot";
import type { Curve, Horizon, IndexAttribution, Pca, SeriesPoint } from "./types";

const POS = "#e06c5a";
const NEG = "#4a90d9";
const INK = "#e6edf3";
const MUTED = "#8b98a8";
const GRID = "#2a3543";
const LINE_COLORS = ["#d4a017", "#4a90d9", "#8b98a8"];

const baseStyle = {
  background: "transparent",
  color: INK,
  fontSize: "11px",
} as const;

const gridColor = { stroke: GRID, strokeOpacity: 0.5 } as const;

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
    style: baseStyle,
    height: 260,
    marginLeft: 44,
    marginRight: 96,
    x: {
      domain: curve.tenors.map((_, i) => i),
      tickFormat: (i: number) => tenorLabels[i] ?? "",
      label: null,
      grid: true,
      ...gridColor,
    },
    y: { label: "Yield (%)", grid: true, ...gridColor },
    color: { domain: points.map((p) => p.label), range: LINE_COLORS, legend: true },
    marks: [
      Plot.line(points, { x: "x", y: "yield", stroke: "label", strokeWidth: 1.8 }),
      Plot.dot(points, { x: "x", y: "yield", fill: "label", r: 3 }),
    ],
  });

  const bars = Plot.plot({
    style: baseStyle,
    height: 150,
    marginLeft: 44,
    marginRight: 96,
    x: {
      domain: curve.tenors.map((_, i) => i),
      tickFormat: (i: number) => tenorLabels[i] ?? "",
      label: "Tenor",
    },
    y: { label: "WoW Δ (bp)", grid: true, ...gridColor },
    marks: [
      Plot.barY(shift, {
        x: "x",
        y: "bp",
        fill: (d: { bp: number | null }) => ((d.bp ?? 0) >= 0 ? POS : NEG),
      }),
      Plot.ruleY([0], { stroke: INK, strokeOpacity: 0.6 }),
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
    style: baseStyle,
    height: 240,
    marginLeft: 44,
    x: { label: "Tenor", domain: pca.loadings.map((r) => String(r.tenor)) },
    y: { label: "Loading", grid: true, ...gridColor },
    color: { domain: ["PC1", "PC2", "PC3"], range: LINE_COLORS, legend: true },
    marks: [
      Plot.line(loadingsLong, {
        x: "tenor",
        y: "value",
        stroke: "pc",
        strokeWidth: 1.8,
      }),
      Plot.dot(loadingsLong, { x: "tenor", y: "value", fill: "pc", r: 3 }),
      Plot.ruleY([0], { stroke: MUTED, strokeOpacity: 0.5 }),
    ],
  });

  const rich = Plot.plot({
    style: baseStyle,
    height: 240,
    marginLeft: 44,
    x: { label: "Tenor", domain: pca.rich_cheap.map((r) => r.tenor) },
    y: { label: "Residual (bp, + = cheap)", grid: true, ...gridColor },
    marks: [
      Plot.barY(pca.rich_cheap, {
        x: "tenor",
        y: "bp",
        fill: (d: { bp: number | null }) => ((d.bp ?? 0) >= 0 ? POS : NEG),
      }),
      Plot.ruleY([0], { stroke: INK, strokeOpacity: 0.6 }),
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
    style: baseStyle,
    height: 300,
    marginLeft: 50,
    marginRight: 20,
    x: { label: null, grid: true, ...gridColor },
    y: { label: "USD/JPY", grid: true, ...gridColor },
    color: {
      domain: ["USD/JPY", "Rate-implied fair value"],
      range: [INK, "#d4a017"],
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
    style: baseStyle,
    height: 26 * rows.length + 44,
    marginLeft: 188,
    marginRight: 44,
    x: { label: "Contribution to index move (pp)", grid: true, ...gridColor },
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
          fill: INK,
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
          fill: INK,
          fontSize: 10,
        },
      ),
      Plot.ruleX([0], { stroke: INK, strokeOpacity: 0.6 }),
    ],
  });
}

/** Horizontal z-score bar chart for the cross-asset momentum heat row. */
export function zscoreBars(
  data: { asset: string; z: number | null }[],
): HTMLElement | SVGSVGElement {
  const rows = data.filter((d) => d.z !== null);
  return Plot.plot({
    style: baseStyle,
    height: 26 * rows.length + 40,
    marginLeft: 78,
    marginRight: 30,
    x: { label: "1W z-score", domain: [-3, 3], grid: true, ...gridColor },
    y: { label: null, domain: rows.map((r) => r.asset) },
    marks: [
      Plot.barX(rows, {
        y: "asset",
        x: "z",
        fill: (d: { z: number | null }) => ((d.z ?? 0) >= 0 ? POS : NEG),
      }),
      Plot.ruleX([0], { stroke: INK, strokeOpacity: 0.6 }),
    ],
  });
}
