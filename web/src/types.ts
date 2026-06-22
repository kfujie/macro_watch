// Shape of web/public/data.json, produced by macro_watch.web_export.

export interface CurveSnapshot {
  label: string;
  date: string;
  yields: (number | null)[];
}

export interface Curve {
  tenors: number[];
  snapshots: CurveSnapshot[];
  wow_shift_bp: (number | null)[];
}

export type Row = Record<string, string | number | null>;

export interface PcaHorizon {
  label: string; // "1M" | "3M" | "6M" | "1Y"
  as_of: string;
  loadings: Row[]; // { tenor, PC1, PC2, PC3 }
  explained: Record<string, number>;
  rich_cheap: { tenor: string; bp: number | null }[];
}

export interface Pca {
  default: string; // label of the horizon shown first
  horizons: PcaHorizon[]; // recomputed per lookback window
}

export interface SeriesPoint {
  date: string;
  value: number | null;
}

export interface ButterflySeries {
  name: string;
  points: SeriesPoint[];
}

export interface Butterflies {
  lookback: number;
  series: ButterflySeries[];
}

export interface Market {
  curve: Curve;
  tenor_table: Row[];
  rates_table: Row[];
  slopes: Butterflies;
  butterflies: Butterflies;
  pca: Pca;
}

export interface VolSeries {
  market: string;
  points: SeriesPoint[];
}

export interface RatesVolatility {
  tenor: number;
  window_days: number;
  horizon_days: number;
  series: VolSeries[];
}

export interface Fx {
  table: Row[];
  usdjpy: SeriesPoint[];
  differential: SeriesPoint[];
  fairvalue: {
    driver: string;
    beta: number | null;
    r2: number | null;
    resid_z: number | null;
    fitted: SeriesPoint[];
    residual: SeriesPoint[];
  };
}

export interface SectorRow {
  sector: string;
  ticker: string;
  weight: number;
  ret_wow: number | null;
  ret_1m: number | null;
  contrib_wow: number | null;
  contrib_1m: number | null;
}

export interface IndexAttribution {
  index_label: string;
  as_of: string;
  level: number;
  index_wow: number;
  index_1m: number;
  prices: SeriesPoint[];
  weights_as_of: string;
  note: string;
  sectors: SectorRow[];
  reconciliation: { sum_contrib_wow: number; sum_contrib_1m: number };
  error?: string;
}

export interface OilVsBei {
  wti: SeriesPoint[];
  bei: SeriesPoint[];
  wti_level: number | null;
  bei_level: number | null;
  corr_60d: number | null;
}

export interface CorrPair {
  a: string;
  b: string;
  corr: number;
  n: number;
}

export interface CorrZPoint {
  date: string;
  a: number | null;
  b: number | null;
}

export interface Correlations {
  window_days: number;
  ranked: CorrPair[];
  highlight: (CorrPair & { series: CorrZPoint[] }) | null;
}

export interface MacroData {
  as_of: string;
  markets: Record<string, Market>;
  rates_volatility: RatesVolatility;
  fx: Fx;
  equities: Record<string, IndexAttribution>;
  rates_correlations: Correlations;
  cross_asset: {
    zscores: { asset: string; z: number | null }[];
    oil_vs_bei: OilVsBei;
    correlations: Correlations;
  };
}

export type Horizon = "wow" | "1m";
