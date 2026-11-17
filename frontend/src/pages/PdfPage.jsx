import { useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Paper,
  Snackbar,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DownloadIcon from "@mui/icons-material/Download";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { api } from "../api";
import Markdown from "../components/Markdown";

const isPdf = (file) => file.type === "application/pdf" || /\.pdf$/i.test(file.name);

export default function PdfPage() {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(null); // name of the file being converted
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null); // {filename, pages, markdown}
  const [view, setView] = useState("preview");
  const [toast, setToast] = useState(null);

  const convert = async (file) => {
    if (!file || busy) return;
    if (!isPdf(file)) {
      setError(`${file.name} is not a PDF`);
      return;
    }
    setBusy(file.name);
    setError(null);
    try {
      setResult(await api.pdfToMarkdown(file));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result.markdown);
      setToast("Markdown copied");
    } catch {
      setToast("Could not copy to the clipboard");
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([result.markdown], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(result.filename || "document").replace(/\.pdf$/i, "")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
      <Stack spacing={2} sx={{ maxWidth: 960, mx: "auto", p: { xs: 2, sm: 3 } }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            PDF to Markdown
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Converted on the server with PyMuPDF4LLM; the PDF isn't sent to Claude. Up to 50 MB.
          </Typography>
        </Box>

        <Paper
          variant="outlined"
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            convert(e.dataTransfer.files?.[0]);
          }}
          sx={{
            p: 4,
            textAlign: "center",
            cursor: busy ? "progress" : "pointer",
            borderStyle: "dashed",
            borderWidth: 2,
            borderColor: dragging ? "primary.main" : "divider",
            bgcolor: (t) => (dragging ? alpha(t.palette.primary.main, 0.06) : "transparent"),
            "&:hover, &:focus-visible": { borderColor: "primary.main", outline: "none" },
          }}
        >
          <UploadFileIcon color="action" sx={{ fontSize: 40 }} />
          <Typography sx={{ mt: 1 }}>
            {busy ? `Converting ${busy}…` : "Drop a PDF here, or click to choose one"}
          </Typography>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(e) => {
              convert(e.target.files?.[0]);
              e.target.value = ""; // allow picking the same file again
            }}
          />
        </Paper>
        {busy && <LinearProgress />}
        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {result && (
          <Paper variant="outlined" sx={{ overflow: "hidden" }}>
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: "center", flexWrap: "wrap", px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}
            >
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography noWrap sx={{ fontWeight: 600 }} title={result.filename}>
                  {result.filename}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {result.pages} page{result.pages === 1 ? "" : "s"} · {result.markdown.length.toLocaleString()}{" "}
                  characters
                </Typography>
              </Box>
              <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
                <ToggleButton value="preview">Preview</ToggleButton>
                <ToggleButton value="markdown">Markdown</ToggleButton>
              </ToggleButtonGroup>
              <Button size="small" startIcon={<ContentCopyIcon />} onClick={copy}>
                Copy
              </Button>
              <Button size="small" startIcon={<DownloadIcon />} onClick={download}>
                Download .md
              </Button>
            </Stack>
            {view === "preview" ? (
              <Box sx={{ px: 3, py: 2 }}>
                {result.markdown.trim() ? (
                  <Markdown>{result.markdown}</Markdown>
                ) : (
                  <Typography color="text.secondary">
                    No text found. The PDF may be scanned images without a text layer.
                  </Typography>
                )}
              </Box>
            ) : (
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 2,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                  fontSize: 13,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {result.markdown}
              </Box>
            )}
          </Paper>
        )}
      </Stack>
      <Snackbar
        open={!!toast}
        autoHideDuration={2500}
        onClose={() => setToast(null)}
        message={toast}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </Box>
  );
}
