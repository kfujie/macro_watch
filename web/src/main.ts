import "./styles.css";
import type { Horizon, IndexAttribution, MacroData, Market } from "./types";
import { applyTimeTheme } from "./theme";
import { card, el, openLightbox, table } from "./ui";
import {
  bflyStats,
  butterflyPanel,
  correlationOverlay,
  curveSnapshot,
  oilVsBei,
  pcaCharts,
  priceTransition,
  sectorContribution,
  SLOPE_COLOR,
  usdjpyVsDifferential,
  zscoreBars,
} from "./charts";

const MARKET_TITLE: Record<string, string> = {
  US: "US Treasury",
  JP: "JGB",
};

type Chart = HTMLElement | SVGSVGElement;

/** A chart container that enlarges into a lightbox when tapped/clicked.
 *  Pass `rebuild` for charts with interactivity (e.g. the curve's value tips)
 *  so the enlarged copy is live rather than a static clone. */
function figure(nodes: Chart[], rebuild?: () => Chart[]): HTMLElement {
  const fig = el("figure", { class: "zoomable", title: "Tap to enlarge" }, nodes);
  fig.addEventListener("click", () => {
    const content = rebuild
      ? el("figure", {}, rebuild())
      : (fig.cloneNode(true) as HTMLElement);
    content.classList.remove("zoomable");
    openLightbox(content);
  });
  return fig;
}

function structureCard(
  serie: { name: string; points: Market["butterflies"]["series"][number]["points"] },
  color?: string,
): HTMLElement {
  const stats = bflyStats(serie.points);
  const titleBits: (Node | string)[] = [el("b", {}, [serie.name])];
  if (stats) {
    titleBits.push(
      el("span", { class: "bfly-meta" }, [
        ` last ${signed(stats.last, 1)} bp · z `,
        el("span", { class: stats.z >= 0 ? "pos" : "neg" }, [signed(stats.z)]),
      ]),
    );
  }
  const body = stats
    ? figure([butterflyPanel(serie.points, stats, color)])
    : el("p", { class: "note" }, ["No data."]);
  return el("div", { class: "card" }, [
    el("div", { class: "card-title" }, titleBits),
    body,
  ]);
}

function marketSection(name: string, m: Market): HTMLElement {
  const title = MARKET_TITLE[name] ?? name;
  const ev = m.pca.explained;
  const pctVar = (k: string) => ((ev[k] ?? 0) * 100).toFixed(1);
  const years = (m.butterflies.lookback / 252).toFixed(1);

  return el("section", {}, [
    el("h2", { class: "section" }, [`${title} — curve, slopes & butterflies`]),

    el("h3", { class: "sub" }, ["Curve snapshot & weekly shift"]),
    figure(curveSnapshot(m.curve), () => curveSnapshot(m.curve)),

    el("div", { class: "grid-2" }, [
      card("Outright tenors", table(m.tenor_table)),
      card("Slopes & butterflies (bp)", table(m.rates_table)),
    ]),

    el("h3", { class: "sub" }, [`Slopes — spread (bp), steeper = up`]),
    el("p", { class: "note" }, [
      `Curve slope (yield_B − yield_A) over ~${years}y, with mean and ±1σ/±2σ bands.`,
    ]),
    el(
      "div",
      { class: "grid-2" },
      m.slopes.series.map((s) => structureCard(s, SLOPE_COLOR)),
    ),

    el("h3", { class: "sub" }, [`Butterflies — spread (bp), belly cheap = up`]),
    el("p", { class: "note" }, [
      `Tenor-weighted fly spread over ~${years}y, with mean and ±1σ/±2σ bands.`,
    ]),
    el(
      "div",
      { class: "grid-2" },
      m.butterflies.series.map((s) => structureCard(s)),
    ),

    el("h3", { class: "sub" }, ["Curve PCA — level / slope / curvature"]),
    el("div", { class: "stat-row" }, [
      el("span", {}, ["Explained variance: "]),
      el("span", {}, [
        "PC1 ",
        el("b", {}, [`${pctVar("PC1")}%`]),
        " · PC2 ",
        el("b", {}, [`${pctVar("PC2")}%`]),
        " · PC3 ",
        el("b", {}, [`${pctVar("PC3")}%`]),
      ]),
    ]),
    el("div", { class: "grid-2" }, [
      card("Factor loadings", figure([pcaCharts(m.pca)[0]!])),
      card("Rich / cheap residual", figure([pcaCharts(m.pca)[1]!])),
    ]),
  ]);
}

function fxSection(data: MacroData): HTMLElement {
  const fv = data.fx.fairvalue;
  const fmt = (v: number | null, d = 2) => (v === null ? "–" : v.toFixed(d));
  return el("section", {}, [
    el("h2", { class: "section" }, ["FX — Dollar & Yen"]),
    card("FX snapshot", table(data.fx.table)),
    el("h3", { class: "sub" }, ["USD/JPY vs the US–JP 10Y differential"]),
    el("div", { class: "stat-row" }, [
      el("span", {}, ["Driver ", el("b", {}, [fv.driver])]),
      el("span", {}, ["β ", el("b", {}, [fmt(fv.beta, 4)])]),
      el("span", {}, ["R² ", el("b", {}, [fmt(fv.r2)])]),
      el("span", {}, ["Resid z ", el("b", {}, [fmt(fv.resid_z)])]),
    ]),
    figure([
      usdjpyVsDifferential(data.fx.usdjpy, fv.fitted),
    ]),
  ]);
}

function signed(v: number, d = 2): string {
  return (v >= 0 ? "+" : "") + v.toFixed(d);
}

function sectorTable(attr: IndexAttribution, horizon: Horizon): HTMLElement {
  const rKey = horizon === "wow" ? "ret_wow" : "ret_1m";
  const cKey = horizon === "wow" ? "contrib_wow" : "contrib_1m";
  const rows = [...attr.sectors].sort(
    (a, b) => (b[cKey] ?? -Infinity) - (a[cKey] ?? -Infinity),
  );
  const head = el("thead", {}, [
    el("tr", {}, [
      el("th", {}, ["Sector"]),
      el("th", {}, ["Weight"]),
      el("th", {}, ["Return"]),
      el("th", {}, ["Contribution"]),
    ]),
  ]);
  const body = el(
    "tbody",
    {},
    rows.map((s) => {
      const ret = s[rKey];
      const con = s[cKey];
      return el("tr", {}, [
        el("td", {}, [s.sector]),
        el("td", {}, [(s.weight * 100).toFixed(1) + "%"]),
        el("td", { class: (ret ?? 0) >= 0 ? "pos" : "neg" }, [
          ret === null ? "–" : signed(ret) + "%",
        ]),
        el("td", { class: (con ?? 0) >= 0 ? "pos" : "neg" }, [
          con === null ? "–" : signed(con) + " pp",
        ]),
      ]);
    }),
  );
  return el("table", {}, [head, body]);
}

function indexBlock(attr: IndexAttribution): HTMLElement {
  let horizon: Horizon = "wow";
  const chartHost = figure([]);
  const tableHost = el("div", {});

  const reconLine = el("div", { class: "stat-row recon" }, []);
  const paint = (): void => {
    const idxMove = horizon === "wow" ? attr.index_wow : attr.index_1m;
    const sum =
      horizon === "wow"
        ? attr.reconciliation.sum_contrib_wow
        : attr.reconciliation.sum_contrib_1m;
    chartHost.replaceChildren(sectorContribution(attr, horizon));
    tableHost.replaceChildren(sectorTable(attr, horizon));
    reconLine.replaceChildren(
      el("span", {}, [
        "Index ",
        el("b", { class: idxMove >= 0 ? "pos" : "neg" }, [signed(idxMove) + "%"]),
      ]),
      el("span", {}, [
        "Σ sector contrib ",
        el("b", { class: sum >= 0 ? "pos" : "neg" }, [signed(sum) + " pp"]),
      ]),
      el("span", { class: "muted-note" }, [
        `residual ${signed(idxMove - sum)} pp (approx. static weights)`,
      ]),
    );
  };

  const mkBtn = (label: string, h: Horizon): HTMLElement => {
    const b = el("button", { class: "toggle" + (h === horizon ? " on" : "") }, [label]);
    b.addEventListener("click", () => {
      horizon = h;
      host.querySelectorAll("button.toggle").forEach((n) => n.classList.remove("on"));
      b.classList.add("on");
      paint();
    });
    return b;
  };

  const statRow = el("div", { class: "stat-row" }, [
    el("span", {}, ["Level ", el("b", {}, [attr.level.toLocaleString("en-US")])]),
    el("span", {}, ["WoW ", el("b", { class: attr.index_wow >= 0 ? "pos" : "neg" }, [
      signed(attr.index_wow) + "%",
    ])]),
    el("span", {}, ["1M ", el("b", { class: attr.index_1m >= 0 ? "pos" : "neg" }, [
      signed(attr.index_1m) + "%",
    ])]),
  ]);

  const toggles = el("div", { class: "toggles" }, [
    mkBtn("WoW", "wow"),
    mkBtn("1M", "1m"),
  ]);

  const noteParts: string[] = [`Weights: ${attr.weights_as_of}.`];
  if (attr.note) noteParts.push(attr.note);
  if (attr.error) noteParts.push(attr.error);

  const priceCard =
    attr.prices && attr.prices.length
      ? card(
          `Price transition (~${(attr.prices.length / 252).toFixed(1)}y)`,
          figure([priceTransition(attr.prices)]),
        )
      : el("div", {});

  const host = el("div", { class: "index-block" }, [
    el("h3", { class: "sub" }, [attr.index_label]),
    statRow,
    priceCard,
    el("h4", { class: "minor" }, ["Sector contribution"]),
    toggles,
    reconLine,
    el("div", { class: "grid-2" }, [
      card("Sector contribution", chartHost),
      card("Sector detail", tableHost),
    ]),
    el("p", { class: "note" }, [noteParts.join(" ")]),
  ]);
  paint();
  return host;
}

function equitiesSection(data: MacroData): HTMLElement {
  return el("section", {}, [
    el("h2", { class: "section" }, ["Equities — S&P 500 & Nikkei 225"]),
    el("p", { class: "note" }, [
      "Index moves decomposed into sector contributions (weight × sector return), " +
        "via SPDR sector ETFs (US) and NEXT FUNDS TOPIX-17 ETFs (Japan).",
    ]),
    ...Object.values(data.equities).map(indexBlock),
  ]);
}

function crossAssetSection(data: MacroData): HTMLElement {
  const ob = data.cross_asset.oil_vs_bei;
  const fmt = (v: number | null, d: number, suffix = "") =>
    v === null ? "–" : v.toFixed(d) + suffix;
  return el("section", {}, [
    el("h2", { class: "section" }, ["Cross-asset backdrop"]),

    el("h3", { class: "sub" }, ["Oil vs breakeven inflation"]),
    el("div", { class: "stat-row" }, [
      el("span", {}, ["WTI ", el("b", {}, [fmt(ob.wti_level, 2, " $/bbl")])]),
      el("span", {}, ["10Y breakeven ", el("b", {}, [fmt(ob.bei_level, 2, "%")])]),
      el("span", {}, [
        "60d corr ",
        el("b", { class: (ob.corr_60d ?? 0) >= 0 ? "pos" : "neg" }, [
          fmt(ob.corr_60d, 2),
        ]),
      ]),
    ]),
    el("p", { class: "note" }, [
      "WTI crude and 10Y breakeven inflation are structurally positively correlated " +
        "(oil feeds inflation expectations); a breakdown flags a demand- vs supply-driven regime.",
    ]),
    figure([oilVsBei(ob)]),

    correlationBlock(
      "Strongest correlation",
      data.cross_asset.correlations,
      CROSS_CORR_NOTE,
    ),

    el("h3", { class: "sub" }, ["1-week momentum (z-scores)"]),
    figure([zscoreBars(data.cross_asset.zscores)]),
  ]);
}

function correlationBlock(
  title: string,
  c: MacroData["cross_asset"]["correlations"],
  note: string,
): HTMLElement {
  const h = c.highlight;
  const children: (Node | string)[] = [
    el("h3", { class: "sub" }, [`${title} (last ${c.window_days}d)`]),
  ];
  if (h) {
    const dir = h.corr >= 0 ? "move together" : "move inversely";
    children.push(
      el("div", { class: "stat-row" }, [
        el("span", {}, [el("b", {}, [h.a]), " vs ", el("b", {}, [h.b])]),
        el("span", {}, [
          "ρ ",
          el("b", { class: h.corr >= 0 ? "pos" : "neg" }, [
            (h.corr >= 0 ? "+" : "") + h.corr.toFixed(2),
          ]),
        ]),
        el("span", { class: "muted-note" }, [`${h.n} sessions · they ${dir}`]),
      ]),
      el("p", { class: "note" }, [note]),
      el("div", { class: "grid-2" }, [
        card("Standardized paths", figure([correlationOverlay(h.series, h.a, h.b)])),
        card("Top pairs by |ρ|", correlationTable(c.ranked)),
      ]),
    );
  } else {
    children.push(el("p", { class: "note" }, ["Insufficient data this window."]));
  }
  return el("div", {}, children);
}

const CROSS_CORR_NOTE =
  "Pearson correlation of daily increments over the last month. Outright rate " +
  "tenors are excluded; curve structures (slopes/butterflies) appear only when " +
  "they co-move with a non-rate asset. Standardized levels shown below.";

const RATES_CORR_NOTE =
  "Co-movement among curve slopes & butterflies (US + JP) over the last month. " +
  "Pairs sharing a tenor leg are excluded (their correlation is mechanical), " +
  "surfacing cross-structure and cross-market relationships.";

function ratesCorrelationSection(data: MacroData): HTMLElement {
  return el("section", {}, [
    el("h2", { class: "section" }, ["Rates — slope & butterfly co-movement"]),
    correlationBlock("Strongest pair", data.rates_correlations, RATES_CORR_NOTE),
  ]);
}

function correlationTable(ranked: MacroData["cross_asset"]["correlations"]["ranked"]): HTMLElement {
  const head = el("thead", {}, [
    el("tr", {}, [
      el("th", {}, ["Pair"]),
      el("th", {}, ["ρ"]),
    ]),
  ]);
  const body = el(
    "tbody",
    {},
    ranked.map((r) =>
      el("tr", {}, [
        el("td", {}, [`${r.a} · ${r.b}`]),
        el("td", { class: r.corr >= 0 ? "pos" : "neg" }, [
          (r.corr >= 0 ? "+" : "") + r.corr.toFixed(3),
        ]),
      ]),
    ),
  );
  return el("table", {}, [head, body]);
}

function render(data: MacroData): void {
  const app = document.getElementById("app")!;
  app.replaceChildren(
    el("header", { class: "brief" }, [
      el("h1", {}, ["Macro Watch — Weekly Rates Brief"]),
      el("span", { class: "as-of" }, [
        `as of ${data.as_of}`,
        el("span", { class: "cadence" }, ["refreshed daily"]),
      ]),
    ]),
    ...Object.entries(data.markets).map(([name, m]) => marketSection(name, m)),
    ratesCorrelationSection(data),
    fxSection(data),
    equitiesSection(data),
    crossAssetSection(data),
  );
}

// Re-apply the time-of-day theme periodically. CSS-variable changes recolor the
// page chrome instantly; charts bake colors into SVG at render time, so they are
// re-rendered only when the daylight factor has shifted enough to matter.
const THEME_INTERVAL_MS = 5 * 60 * 1000;
let currentData: MacroData | null = null;
let lastFactor = -1;

function tickTheme(): void {
  const t = applyTimeTheme(new Date());
  if (currentData && Math.abs(t - lastFactor) > 0.02) {
    render(currentData);
    lastFactor = t;
  }
}

async function boot(): Promise<void> {
  lastFactor = applyTimeTheme(new Date()); // theme the loading screen too
  try {
    // BASE_URL is "/" in dev and the configured base (e.g. "/macro_watch/") in a
    // GitHub Pages build, so data.json resolves correctly under a subpath.
    const res = await fetch(`${import.meta.env.BASE_URL}data.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    currentData = (await res.json()) as MacroData;
    render(currentData);
    window.setInterval(tickTheme, THEME_INTERVAL_MS);
  } catch (err) {
    const app = document.getElementById("app")!;
    app.replaceChildren(
      el("p", { class: "loading" }, [
        `Failed to load data.json (${String(err)}). ` +
          "Run: uv run python -m macro_watch.web_export",
      ]),
    );
  }
}

void boot();
