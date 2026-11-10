import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Box, Link } from "@mui/material";
import { citeNumbers } from "../citations";
import { levelTextSx } from "../sources";

// Our own link targets: "cite:1,2" (sourced text) and "conf:85" (Claude's own statement, 85% confident).
const isMarker = (url) => url.startsWith("cite:") || url.startsWith("conf:");
const keepMarkerUrls = (url) => (isMarker(url) ? url : defaultUrlTransform(url));

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

export default function Markdown({ children, refs = new Map() }) {
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
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={keepMarkerUrls}
        components={{
          a: ({ href = "", children: text, node: _node, ...props }) =>
            href.startsWith("cite:") ? (
              <Cited numbers={citeNumbers(href)} refs={refs}>
                {text}
              </Cited>
            ) : href.startsWith("conf:") ? (
              <Confident value={href.slice("conf:".length)}>{text}</Confident>
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
