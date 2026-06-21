import type { Row } from "./types";

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  children: (Node | string)[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    node.append(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

const fmtNum = (v: number, decimals: number): string =>
  v.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

/** Per-column formatting rules keyed by a substring of the header. */
function formatCell(col: string, v: string | number | null): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "string") return v;
  if (col.includes("bp") || col === "1M(bp)" || col === "WoW(bp)")
    return (v >= 0 ? "+" : "") + fmtNum(v, 0);
  if (col.startsWith("Z_")) return (v >= 0 ? "+" : "") + fmtNum(v, 2);
  if (col.includes("%")) return (v >= 0 ? "+" : "") + fmtNum(v, 2);
  if (col === "Pctile") return fmtNum(v, 0);
  if (col === "Level" || col === "Level(bp)") return fmtNum(v, v >= 100 ? 2 : 1);
  return fmtNum(v, 3);
}

/** Columns whose sign should be colored red(+)/blue(−). */
const SIGNED = (c: string): boolean =>
  c.startsWith("Z_") ||
  c.includes("bp") ||
  c.includes("%") ||
  c === "WoW";

export function table(rows: Row[], columns?: string[]): HTMLElement {
  if (rows.length === 0) return el("p", { class: "loading" }, ["No data."]);
  const cols = columns ?? Object.keys(rows[0]!);
  const head = el(
    "thead",
    {},
    [el("tr", {}, cols.map((c) => el("th", {}, [c])))],
  );
  const body = el(
    "tbody",
    {},
    rows.map((r) =>
      el(
        "tr",
        {},
        cols.map((c) => {
          const v = r[c] ?? null;
          const cls =
            SIGNED(c) && typeof v === "number"
              ? v >= 0
                ? "pos"
                : "neg"
              : "";
          return el("td", cls ? { class: cls } : {}, [formatCell(c, v)]);
        }),
      ),
    ),
  );
  return el("table", {}, [head, body]);
}

export function card(title: string, body: Node): HTMLElement {
  return el("div", { class: "card" }, [
    el("div", { class: "card-title" }, [title]),
    body as Node,
  ]);
}

// --- Lightbox: tap a figure to enlarge it -----------------------------------
let lightboxEl: HTMLElement | null = null;

function ensureLightbox(): HTMLElement {
  if (lightboxEl) return lightboxEl;
  const inner = el("div", { class: "lightbox-inner" });
  const overlay = el(
    "div",
    { class: "lightbox", role: "dialog", "aria-modal": "true" },
    [inner, el("div", { class: "lightbox-hint" }, ["tap anywhere to close"])],
  );
  overlay.addEventListener("click", closeLightbox);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
  });
  document.body.append(overlay);
  lightboxEl = overlay;
  return overlay;
}

export function closeLightbox(): void {
  lightboxEl?.classList.remove("open");
}

/** Show a (cloned) node enlarged in a full-screen overlay. */
export function openLightbox(content: Node): void {
  const overlay = ensureLightbox();
  (overlay.firstElementChild as HTMLElement).replaceChildren(content);
  overlay.classList.add("open");
}
