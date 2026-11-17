import { useEffect, useRef, useState } from "react";
import {
  Box,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import CodeIcon from "@mui/icons-material/Code";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DownloadIcon from "@mui/icons-material/Download";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import Markdown from "./Markdown";

const RECT_KEY = "paperViewerRect";
const MIN_W = 360;
const MIN_H = 280;
const MARGIN = 8;
// Above the app bar and side drawer, below dialogs and menus.
const Z_INDEX = 1250;

const mono = { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 13 };

function defaultRect() {
  const w = Math.min(760, Math.round(window.innerWidth * 0.48));
  return { x: window.innerWidth - w - 24, y: 104, w, h: window.innerHeight - 128 };
}

function readRect() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECT_KEY));
    if (saved && ["x", "y", "w", "h"].every((k) => Number.isFinite(saved[k]))) return saved;
  } catch {
    // No saved position (or storage unavailable): use the default.
  }
  return defaultRect();
}

/** Keep the window on screen (e.g. after the browser window shrinks). */
function clamp({ x, y, w, h }) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.max(MIN_W, Math.min(w, vw - 2 * MARGIN));
  const height = Math.max(MIN_H, Math.min(h, vh - 2 * MARGIN));
  return {
    w: width,
    h: height,
    x: Math.min(Math.max(MARGIN, x), vw - width - MARGIN),
    y: Math.min(Math.max(MARGIN, y), vh - height - MARGIN),
  };
}

/**
 * A floating, non-modal window showing a paper: the original PDF (the browser's viewer) or the Markdown it was
 * converted to. Drag it by its title bar, resize it from the bottom-right corner; on phones it fills the screen.
 * `target` ({page, nonce}) opens the PDF at a page; a new nonce re-opens even the same page.
 */
export default function PaperViewer({ paper, pdfUrl, view, onViewChange, target, onClose, onToast }) {
  // The paper's Markdown links its images as images/<file>; the API serves them under the paper.
  const imageBase = paper ? `/api/papers/${paper.id}/` : undefined;
  const isDesktop = useMediaQuery((theme) => theme.breakpoints.up("md"));
  const [rect, setRect] = useState(() => clamp(readRect()));
  const [moving, setMoving] = useState(false); // dragging or resizing: the PDF frame mustn't swallow the pointer
  const [raw, setRaw] = useState(false);
  const gesture = useRef(null);

  useEffect(() => {
    const onResize = () => setRect((r) => clamp(r));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const start = (kind) => (e) => {
    if (!isDesktop || e.button !== 0) return;
    if (kind === "move" && e.target.closest("button")) return; // the title bar's buttons stay clickable
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    gesture.current = { kind, startX: e.clientX, startY: e.clientY, rect };
    setMoving(true);
  };
  const move = (e) => {
    const g = gesture.current;
    if (!g) return;
    const dx = e.clientX - g.startX;
    const dy = e.clientY - g.startY;
    setRect(
      clamp(
        g.kind === "move"
          ? { ...g.rect, x: g.rect.x + dx, y: g.rect.y + dy }
          : { ...g.rect, w: g.rect.w + dx, h: g.rect.h + dy }
      )
    );
  };
  const end = () => {
    if (!gesture.current) return;
    gesture.current = null;
    setMoving(false);
    setRect((r) => {
      try {
        localStorage.setItem(RECT_KEY, JSON.stringify(r));
      } catch {
        // Storage unavailable: the position just isn't remembered.
      }
      return r;
    });
  };

  const markdown = paper?.markdown ?? "";
  // Copied or downloaded Markdown leaves the app, so its image links become full URLs.
  const portable = () =>
    markdown.replace(/(!\[[^\]]*\]\()images\//g, `$1${window.location.origin}${imageBase}images/`);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(portable());
      onToast("Markdown copied");
    } catch {
      onToast("Could not copy to the clipboard");
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([portable()], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(paper?.filename || "paper").replace(/\.pdf$/i, "")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const placement = isDesktop
    ? { left: rect.x, top: rect.y, width: rect.w, height: rect.h }
    : { inset: 0, width: "100%", height: "100%", borderRadius: 0 };

  return (
    <Paper
      elevation={12}
      role="dialog"
      aria-label={`Paper: ${paper?.title ?? ""}`}
      sx={{
        position: "fixed",
        zIndex: Z_INDEX,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
        ...placement,
      }}
    >
      <Stack
        direction="row"
        spacing={1}
        onPointerDown={start("move")}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        sx={{
          alignItems: "center",
          px: 1.5,
          py: 0.75,
          borderBottom: 1,
          borderColor: "divider",
          bgcolor: "action.hover",
          cursor: isDesktop ? (moving ? "grabbing" : "grab") : "default",
          userSelect: "none",
          touchAction: "none",
        }}
      >
        <Typography noWrap variant="subtitle2" sx={{ flex: 1, minWidth: 0, fontWeight: 600 }} title={paper?.title}>
          {paper?.title ?? "Loading…"}
        </Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={view}
          onChange={(_, v) => v && onViewChange(v)}
          aria-label="Show"
          sx={{ "& .MuiToggleButton-root": { py: 0.25, px: 1.25, textTransform: "none" } }}
        >
          <ToggleButton value="pdf">PDF</ToggleButton>
          <ToggleButton value="markdown">Markdown</ToggleButton>
        </ToggleButtonGroup>
        {view === "pdf" ? (
          <Tooltip title="Open the PDF in a new tab">
            <IconButton size="small" component="a" href={pdfUrl} target="_blank" rel="noopener noreferrer">
              <OpenInNewIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : (
          <>
            <Tooltip title={raw ? "Show formatted" : "Show Markdown source"}>
              <IconButton size="small" onClick={() => setRaw((r) => !r)} color={raw ? "primary" : "default"}>
                <CodeIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Copy Markdown">
              <IconButton size="small" onClick={copy} disabled={!markdown}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Download .md">
              <IconButton size="small" onClick={download} disabled={!markdown}>
                <DownloadIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </>
        )}
        <Tooltip title="Hide paper">
          <IconButton size="small" onClick={onClose} aria-label="Hide paper">
            <CloseIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      <Box sx={{ flex: 1, minHeight: 0, position: "relative", bgcolor: "background.paper" }}>
        {view === "pdf" ? (
          <Box
            component="iframe"
            // A new key reloads the frame, so "#page=N" jumps even when only the page changes.
            key={`${pdfUrl}-${target.nonce}`}
            src={`${pdfUrl}#page=${target.page}`}
            title={`PDF: ${paper?.title ?? ""}`}
            sx={{ border: 0, width: "100%", height: "100%", display: "block", pointerEvents: moving ? "none" : "auto" }}
          />
        ) : !paper?.markdown && paper?.markdown !== "" ? (
          <Stack sx={{ height: "100%", alignItems: "center", justifyContent: "center" }}>
            <CircularProgress size={28} />
          </Stack>
        ) : (
          <Box sx={{ height: "100%", overflowY: "auto", px: 3, py: 2 }}>
            {!markdown.trim() ? (
              <Typography color="text.secondary">
                No text found. The PDF may be scanned images without a text layer.
              </Typography>
            ) : raw ? (
              <Box component="pre" sx={{ ...mono, m: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {markdown}
              </Box>
            ) : (
              <Markdown imageBase={imageBase}>{markdown}</Markdown>
            )}
          </Box>
        )}
      </Box>

      {isDesktop && (
        <Box
          onPointerDown={start("resize")}
          onPointerMove={move}
          onPointerUp={end}
          onPointerCancel={end}
          aria-hidden
          sx={{
            position: "absolute",
            right: 0,
            bottom: 0,
            width: 18,
            height: 18,
            cursor: "nwse-resize",
            touchAction: "none",
            // A small corner grip.
            background: (t) =>
              `linear-gradient(135deg, transparent 50%, ${t.palette.text.disabled} 50%, ${t.palette.text.disabled} 60%, transparent 60%, transparent 70%, ${t.palette.text.disabled} 70%, ${t.palette.text.disabled} 80%, transparent 80%)`,
          }}
        />
      )}
    </Paper>
  );
}
