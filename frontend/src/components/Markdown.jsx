import { createContext, useContext } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Box, Link } from "@mui/material";
import { citeNumbers } from "../citations";
import { levelTextSx } from "../sources";

// Our own link targets: "cite:1,2" (sourced text), "conf:85" (Claude's own statement, 85% confident) and
// "page:4" (page 4 of the paper a Papers-tab chat is about).
const isMarker = (url) => url.startsWith("cite:") || url.startsWith("conf:") || url.startsWith("page:");

/** Opens the paper at a page, for "page:N" links: provided by the Papers tab, null elsewhere. */
export const PageLinkContext = createContext(null);

/** "[p. 4](page:4)": a button that opens the paper's PDF at that page; plain text outside the Papers tab. */
function PageLink({ page, children }) {
  const openPage = useContext(PageLinkContext);
  if (!openPage || !Number.isInteger(page) || page < 1) return <span>{children}</span>;
  return (
    <Link
      component="button"
      type="button"
      onClick={() => openPage(page)}
      title={`Open the PDF at page ${page}`}
      underline="hover"
      sx={{ font: "inherit", verticalAlign: "baseline", fontWeight: 500 }}
    >
      {children}
    </Link>
  );
}
const keepMarkerUrls = (url) => (isMarker(url) ? url : defaultUrlTransform(url));
// A relative link: no scheme ("https:", "data:"…), not from the site root, not a fragment.
const isRelative = (url) => !/^[a-z][a-z\d+.-]*:/i.test(url) && !url.startsWith("/") && !url.startsWith("#");

/** Claude's own statement: normal text color, followed by its confidence as a small badge. */
function Confident({ value, children }) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(value))));
  if (!Number.isFinite(pct)) return children;
  return (
    <>
      {children}
      <Box
        component="span"
        title={`Claude's own statement (not from a source) · confidence ${pct}%`}
        sx={{
          display: "inline-block",
          ml: 0.5,
          px: 0.5,
          border: 1,
          borderColor: "divider",
          borderStyle: pct < 50 ? "dashed" : "solid",
          borderRadius: 1,
          fontSize: "0.72em",
          lineHeight: 1.4,
          color: "text.secondary",
          verticalAlign: "0.1em",
          whiteSpace: "nowrap",
        }}
      >
        {pct}%
      </Box>
    </>
  );
}

/**
 * Text Claude took from sources, colored by the most credible cited source's level, then "[1, 2]".
 * Unrated sources (not on the Source tab) keep the normal color with a dotted underline.
 */
function Cited({ numbers, refs, children }) {
  const cited = numbers.map((n) => ({ n, ref: refs.get(n) }));
  const levels = cited.map((c) => c.ref?.level).filter(Boolean);
  const level = levels.length ? Math.min(...levels) : null;
  const known = cited.some((c) => c.ref);
  const tooltip = cited
    .filter((c) => c.ref)
    .map((c) => `[${c.n}] ${c.ref.level ? `Lv${c.ref.level}` : "Unrated"} · ${c.ref.host ?? c.ref.url}`)
    .join("\n");

  return (
    <>
      <Box
        component="span"
        title={tooltip || undefined}
        sx={
          level
            ? levelTextSx(level)
            : known
              ? { textDecoration: "underline dotted", textUnderlineOffset: "3px", textDecorationColor: "currentColor" }
              : undefined
        }
      >
        {children}
      </Box>
      <Box component="span" sx={{ ml: 0.4, fontSize: "0.8em", color: "text.secondary", whiteSpace: "nowrap" }}>
        [
        {cited.map(({ n, ref }, i) => (
          <span key={n}>
            {i > 0 && ", "}
            {ref ? (
              <Link href={ref.url} target="_blank" rel="noopener noreferrer" underline="hover" title={ref.title}>
                {n}
              </Link>
            ) : (
              n
            )}
          </span>
        ))}
        ]
      </Box>
    </>
  );
}

/**
 * `imageBase` resolves relative image links, e.g. "/api/papers/1/" turns images/fig.png into
 * /api/papers/1/images/fig.png (a paper's Markdown links its images next to it).
 */
export default function Markdown({ children, refs = new Map(), imageBase }) {
  const transform = (url, key) =>
    imageBase && key === "src" && isRelative(url) ? defaultUrlTransform(imageBase + url) : keepMarkerUrls(url);

  return (
    <Box
      sx={{
        "& > :first-of-type": { mt: 0 },
        "& > :last-child": { mb: 0 },
        "& p": { my: 1, lineHeight: 1.7 },
        "& a": { color: "primary.main" },
        "& code": {
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: "0.875em",
          bgcolor: "action.hover",
          px: 0.5,
          borderRadius: 0.5,
        },
        "& pre": {
          bgcolor: "action.hover",
          p: 1.5,
          borderRadius: 1,
          overflowX: "auto",
          "& code": { bgcolor: "transparent", p: 0 },
        },
        "& table": { borderCollapse: "collapse", my: 1 },
        "& th, & td": { border: 1, borderColor: "divider", px: 1, py: 0.5 },
        "& blockquote": { borderLeft: 3, borderColor: "divider", pl: 2, ml: 0, color: "text.secondary" },
        // Figures: never wider than the text; a white backdrop, since most are drawn for white paper.
        "& img": { display: "block", maxWidth: "100%", height: "auto", my: 1.5, mx: "auto", bgcolor: "#fff", borderRadius: 0.5 },
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={transform}
        components={{
          a: ({ href = "", children: text, node: _node, ...props }) =>
            href.startsWith("cite:") ? (
              <Cited numbers={citeNumbers(href)} refs={refs}>
                {text}
              </Cited>
            ) : href.startsWith("conf:") ? (
              <Confident value={href.slice("conf:".length)}>{text}</Confident>
            ) : href.startsWith("page:") ? (
              <PageLink page={Number.parseInt(href.slice("page:".length), 10)}>{text}</PageLink>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                {text}
              </a>
            ),
        }}
      >
        {children}
      </ReactMarkdown>
    </Box>
  );
}
