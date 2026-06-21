import "./styles.css";
import type { Horizon, IndexAttribution, MacroData, Market } from "./types";
import { card, el, table } from "./ui";
import {
  curveSnapshot,
  pcaCharts,
  sectorContribution,
  usdjpyVsDifferential,
  zscoreBars,
} from "./charts";

const MARKET_TITLE: Record<string, string> = {
  US: "US Treasury",
  JP: "JGB",
};

function figure(nodes: (HTMLElement | SVGSVGElement)[]): HTMLElement {
  return el("figure", {}, nodes);
}

function marketSection(name: string, m: Market): HTMLElement {
  const title = MARKET_TITLE[name] ?? name;
  const ev = m.pca.explained;
  const pctVar = (k: string) => ((ev[k] ?? 0) * 100).toFixed(1);

  return el("section", {}, [
    el("h2", { class: "section" }, [`${title} — curve, slopes & butterflies`]),

    el("h3", { class: "sub" }, ["Curve snapshot & weekly shift"]),
    figure(curveSnapshot(m.curve)),

    el("div", { class: "grid-2" }, [
      card("Outright tenors", table(m.tenor_table)),
      card("Slopes & butterflies (bp)", table(m.rates_table)),
    ]),

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
  const chartHost = el("figure", {});
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

  const host = el("div", { class: "index-block" }, [
    el("h3", { class: "sub" }, [attr.index_label]),
    statRow,
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
  return el("section", {}, [
    el("h2", { class: "section" }, ["Cross-asset backdrop"]),
    el("h3", { class: "sub" }, ["1-week momentum (z-scores)"]),
    figure([zscoreBars(data.cross_asset.zscores)]),
  ]);
}

function render(data: MacroData): void {
  const app = document.getElementById("app")!;
  app.replaceChildren(
    el("header", { class: "brief" }, [
      el("h1", {}, ["Macro Watch — Weekly Rates Brief"]),
      el("span", { class: "as-of" }, [`as of ${data.as_of}`]),
    ]),
    ...Object.entries(data.markets).map(([name, m]) => marketSection(name, m)),
    fxSection(data),
    equitiesSection(data),
    crossAssetSection(data),
  );
}

async function boot(): Promise<void> {
  try {
    const res = await fetch("/data.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render((await res.json()) as MacroData);
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
