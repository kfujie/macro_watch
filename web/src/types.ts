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

export interface Pca {
  as_of: string;
  loadings: Row[]; // { tenor, PC1, PC2, PC3 }
  explained: Record<string, number>;
  rich_cheap: { tenor: string; bp: number | null }[];
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
  butterflies: Butterflies;
  pca: Pca;
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

export interface MacroData {
  as_of: string;
  markets: Record<string, Market>;
  fx: Fx;
  equities: Record<string, IndexAttribution>;
  cross_asset: {
    zscores: { asset: string; z: number | null }[];
    oil_vs_bei: OilVsBei;
  };
}

export type Horizon = "wow" | "1m";
