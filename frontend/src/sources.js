import { createContext, useContext } from "react";

// Solid colors for badges and borders, one per credibility level: green (most credible) → red (least).
export const LEVEL_COLORS = { 1: "#2e7d32", 2: "#1565c0", 3: "#ef6c00", 4: "#c62828" };

// Text colors with enough contrast on the page background in each color scheme.
const TEXT_COLORS = {
  light: { 1: "#2e7d32", 2: "#1565c0", 3: "#a85d00", 4: "#c62828" },
  dark: { 1: "#81c784", 2: "#64b5f6", 3: "#ffb74d", 4: "#e57373" },
};

/** sx for text colored by credibility level (works in light and dark mode). */
export const levelTextSx = (level) => (theme) => ({
  color: TEXT_COLORS.light[level],
  ...theme.applyStyles("dark", { color: TEXT_COLORS.dark[level] }),
});

/** The Source tab's list, shared with the chat so cited text can be colored. */
export const SourcesContext = createContext([]);
export const useSources = () => useContext(SourcesContext);

export function hostnameOf(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return null;
  }
}

/**
 * How a source name matches hostnames:
 *   ".gov"          suffix: whitehouse.gov, data.gov.tw
 *   "bbc.com"       domain and its subdomains: bbc.com, news.bbc.com
 *   "WhatsApp"      a hostname label: whatsapp.com, chat.whatsapp.com
 *   "PTT (ptt.cc)"  the domain, plus the other words as labels
 * Multi-word names without a domain ("Content farms") match nothing.
 */
function patternsFor(name) {
  const tokens = name.toLowerCase().split(/[\s(),（）]+/).filter(Boolean);
  const hasDomain = tokens.some((t) => t.includes("."));
  return tokens.flatMap((t) => {
    if (t.startsWith(".")) return [{ kind: "suffix", value: t }];
    if (t.includes(".")) return [{ kind: "domain", value: t }];
    if (tokens.length === 1 || hasDomain) return [{ kind: "label", value: t }];
    return [];
  });
}

function score(host, { kind, value }) {
  switch (kind) {
    case "domain":
      return host === value || host.endsWith(`.${value}`) ? 100 + value.length : 0;
    case "label":
      return host.split(".").includes(value) ? 50 : 0;
    case "suffix":
      return host.endsWith(value) || host.includes(`${value}.`) ? value.length : 0;
    default:
      return 0;
  }
}

/** The most specific source matching a URL (so "npr.org" beats ".org"), or null if unrated. */
export function matchSource(url, sources) {
  const host = hostnameOf(url);
  if (!host) return null;
  let best = null;
  let bestScore = 0;
  for (const source of sources) {
    for (const pattern of patternsFor(source.name)) {
      const s = score(host, pattern);
      if (s > bestScore) {
        best = source;
        bestScore = s;
      }
    }
  }
  return best;
}
