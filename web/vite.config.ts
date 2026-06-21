import { defineConfig } from "vite";

// Served from a subpath on GitHub Pages (kfujie.github.io/macro_watch/). CI sets
// VITE_BASE=/macro_watch/; local dev and preview default to "/" (domain root).
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
});
