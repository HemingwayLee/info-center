import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  ListItemIcon,
  Menu,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { api, applyEvent, newTurn, streamMessage, watchTurn } from "../api";
import Composer from "../components/Composer";
import { PageLinkContext } from "../components/Markdown";
import PaperSidebar from "../components/PaperSidebar";
import PaperViewer from "../components/PaperViewer";
import TurnItem from "../components/TurnItem";
import SplitLayout from "../layout/SplitLayout";

const CHAT_MAX_WIDTH = 1000;
const SELECTED_KEY = "paperSelected";

// One click to start, for readers who find the paper hard going.
const STARTERS = [
  "Explain the key ideas in plain language",
  "What problem does it solve, and why does it matter?",
  "Walk me through the method step by step",
  "What are the main results, and how strong is the evidence?",
  "What are the limitations and open questions?",
  "Explain the hardest part with a simple example",
];

const isPdf = (file) => file.type === "application/pdf" || /\.pdf$/i.test(file.name);
const pdfUrl = (id) => `/api/papers/${id}/pdf`;

function readSelected() {
  try {
    return Number(localStorage.getItem(SELECTED_KEY)) || null;
  } catch {
    return null;
  }
}

function saveSelected(id) {
  try {
    localStorage.setItem(SELECTED_KEY, String(id ?? ""));
  } catch {
    // Storage unavailable: the selection just isn't remembered.
  }
}

/**
 * A paper's chat: its saved turns and the answer being written, over the normal conversation endpoints.
 * Switching papers stops watching the answer in progress; it keeps going on the server and shows when you return.
 */
function usePaperChat(conversationId, onSaved) {
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState(null);
  const [model, setModel] = useState("");
  const abortRef = useRef(null);
  const currentRef = useRef(conversationId);
  currentRef.current = conversationId;

  const detach = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setDraft(null);
  };

  const follow = async (id, initial, run) => {
    let final = initial;
    setDraft(final);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await run((event) => {
        final = applyEvent(final, event);
        if (!controller.signal.aborted) setDraft(final);
      }, controller.signal);
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
    }
    if (controller.signal.aborted) return;
    abortRef.current = null;
    setDraft(null);
    if (currentRef.current === id) {
      if (final.id != null) setTurns((prev) => [...prev, final]);
      else load(id); // the stream broke before the answer was saved: ask the server
    }
    onSaved?.();
  };

  const load = async (id) => {
    try {
      const convo = await api.getConversation(id);
      if (currentRef.current !== id) return;
      setModel(convo.model);
      const last = convo.turns.at(-1);
      if (last?.status === "running") {
        setTurns(convo.turns.slice(0, -1));
        const initial = { ...newTurn(last.question, { research: false, model: last.model }), turnId: last.id };
        follow(id, initial, (onEvent, signal) => watchTurn(last.id, { onEvent, signal }));
      } else {
        setTurns(convo.turns);
      }
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    detach();
    setTurns([]);
    setError(null);
    if (conversationId) load(conversationId);
    return () => abortRef.current?.abort();
  }, [conversationId]); // only when the paper changes; load/detach are recreated every render

  const send = (text) => {
    setError(null);
    const id = conversationId;
    return follow(id, newTurn(text, { research: false, model }), (onEvent, signal) =>
      streamMessage(id, text, { research: false, signal, onEvent })
    );
  };

  const stop = async () => {
    if (!draft?.turnId) return;
    try {
      await api.cancelTurn(draft.turnId);
    } catch (e) {
      setError(`Couldn't stop: ${e.message}`);
    }
  };

  const changeModel = async (value) => {
    setModel(value);
    try {
      await api.updateConversation(conversationId, { model: value });
    } catch (e) {
      setError(`Couldn't change the model: ${e.message}`);
    }
  };

  return { turns, setTurns, draft, error, setError, model, changeModel, send, stop };
}

/** Big drop target, shown when there are no papers yet. */
function DropZone({ onAdd }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  return (
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
        onAdd([...(e.dataTransfer.files ?? [])]);
      }}
      sx={{
        p: 5,
        textAlign: "center",
        cursor: "pointer",
        borderStyle: "dashed",
        borderWidth: 2,
        borderColor: dragging ? "primary.main" : "divider",
        bgcolor: (t) => (dragging ? alpha(t.palette.primary.main, 0.06) : "transparent"),
        "&:hover, &:focus-visible": { borderColor: "primary.main", outline: "none" },
      }}
    >
      <UploadFileIcon color="action" sx={{ fontSize: 44 }} />
      <Typography sx={{ mt: 1, fontWeight: 600 }}>Drop a PDF here, or click to choose one</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        It&apos;s converted to Markdown on the server (up to 50 MB), then you can ask Claude about it.
      </Typography>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        onChange={(e) => {
          onAdd([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />
    </Paper>
  );
}

export default function PapersPage({ active = true }) {
  const [papers, setPapers] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [uploads, setUploads] = useState([]); // [{key, name}] being converted
  const [selectedId, setSelectedId] = useState(readSelected);
  const [details, setDetails] = useState({}); // paper id -> detail with markdown, loaded when first shown
  const [models, setModels] = useState([]);
  const [promptHistory, setPromptHistory] = useState([]);
  const [viewer, setViewer] = useState({ open: false, view: "pdf", page: 1, nonce: 0 });
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [pageError, setPageError] = useState(null);
  const [toast, setToast] = useState(null);
  const bottomRef = useRef(null);

  const paper = papers.find((p) => p.id === selectedId) ?? null;

  const refreshPapers = useCallback(async () => {
    try {
      setPapers(await api.listPapers());
    } catch (e) {
      setPageError(`Cannot load papers: ${e.message}`);
    } finally {
      setLoaded(true);
    }
  }, []);

  const chat = usePaperChat(paper?.conversation_id ?? null, refreshPapers);
  const streaming = chat.draft !== null;

  useEffect(() => {
    refreshPapers();
    api
      .models()
      .then(({ models }) => setModels(models))
      .catch(() => {});
  }, [refreshPapers]);

  useEffect(() => {
    if (active)
      api
        .promptHistory()
        .then(setPromptHistory)
        .catch(() => {});
  }, [active]);

  // Select the remembered paper, or the newest, once the list arrives (and after the selected one is deleted).
  useEffect(() => {
    if (!loaded) return;
    if (!papers.some((p) => p.id === selectedId)) setSelectedId(papers[0]?.id ?? null);
  }, [loaded, papers, selectedId]);

  useEffect(() => saveSelected(selectedId), [selectedId]);

  // The Markdown is only needed for the viewer; fetch it the first time a paper is shown there.
  useEffect(() => {
    if (!viewer.open || !paper || details[paper.id]) return;
    api
      .getPaper(paper.id)
      .then((d) => setDetails((all) => ({ ...all, [d.id]: d })))
      .catch((e) => setToast(`Couldn't load the Markdown: ${e.message}`));
  }, [viewer.open, paper, details]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [chat.turns, chat.draft]);

  const select = (id) => {
    setSelectedId(id);
    setViewer((v) => ({ ...v, page: 1, nonce: v.nonce + 1 }));
  };

  const add = async (files) => {
    const pdfs = files.filter(isPdf);
    if (pdfs.length < files.length) setToast("Only PDF files can be added");
    for (const file of pdfs) {
      const key = `${file.name}-${file.size}-${Date.now()}`;
      setUploads((u) => [...u, { key, name: file.name }]);
      try {
        const made = await api.uploadPaper(file);
        setPapers((list) => [made, ...list.filter((p) => p.id !== made.id)]);
        setSelectedId(made.id);
      } catch (e) {
        setPageError(`${file.name}: ${e.message}`);
      } finally {
        setUploads((u) => u.filter((x) => x.key !== key));
      }
    }
  };

  const rename = async (id, title) => {
    const previous = papers;
    setPapers((list) => list.map((p) => (p.id === id ? { ...p, title } : p)));
    try {
      await api.renamePaper(id, title);
      setDetails((all) => (all[id] ? { ...all, [id]: { ...all[id], title } } : all));
    } catch (e) {
      setPapers(previous);
      setPageError(`Couldn't rename the paper: ${e.message}`);
    }
  };

  const remove = async (id) => {
    try {
      await api.deletePaper(id); // also stops an answer being written
      setPapers((list) => list.filter((p) => p.id !== id));
    } catch (e) {
      setPageError(`Couldn't delete the paper: ${e.message}`);
    }
  };

  const clearChat = async () => {
    setMenuAnchor(null);
    try {
      const updated = await api.clearPaperChat(paper.id);
      chat.setTurns([]);
      setPapers((list) => list.map((p) => (p.id === updated.id ? updated : p)));
    } catch (e) {
      chat.setError(e.message);
    }
  };

  const send = (text) => {
    setPromptHistory((prev) => (prev[0] === text ? prev : [text, ...prev]));
    chat.send(text);
  };

  const openPage = useCallback(
    (page) => setViewer((v) => ({ open: true, view: "pdf", page, nonce: v.nonce + 1 })),
    []
  );

  const empty = chat.turns.length === 0 && !streaming;
  const error = pageError ?? chat.error;
  const clearError = () => (pageError ? setPageError(null) : chat.setError(null));
  const errorAlert = error && (
    <Alert severity="error" sx={{ mb: 1.5 }} onClose={clearError}>
      {error}
    </Alert>
  );
  const composer = (autoFocus) => (
    <Composer
      onSend={send}
      onStop={chat.stop}
      streaming={streaming}
      history={promptHistory}
      placeholder="Ask about this paper"
      autoFocus={autoFocus}
    />
  );

  return (
    <PageLinkContext.Provider value={paper ? openPage : null}>
      <SplitLayout
        sidebar={
          <PaperSidebar
            papers={papers}
            uploads={uploads}
            currentId={selectedId}
            onSelect={select}
            onAdd={add}
            onRename={rename}
            onDelete={remove}
          />
        }
        header={
          paper && (
            <Stack direction="row" spacing={1} sx={{ flex: 1, minWidth: 0, alignItems: "center" }}>
              <Typography noWrap sx={{ flex: 1, minWidth: 0, fontWeight: 600 }} title={paper.title}>
                {paper.title}
              </Typography>
              <Select
                size="small"
                variant="standard"
                disableUnderline
                value={models.some((m) => m.id === chat.model) ? chat.model : ""}
                onChange={(e) => chat.changeModel(e.target.value)}
                disabled={streaming}
                sx={{ fontSize: 14, display: { xs: "none", sm: "inline-flex" } }}
              >
                {models.map((m) => (
                  <MenuItem key={m.id} value={m.id}>
                    {m.name}
                  </MenuItem>
                ))}
              </Select>
              <Button
                size="small"
                variant={viewer.open ? "contained" : "outlined"}
                startIcon={<ArticleOutlinedIcon />}
                onClick={() => setViewer((v) => ({ ...v, open: !v.open }))}
                aria-pressed={viewer.open}
                sx={{ flexShrink: 0 }}
              >
                {viewer.open ? "Hide paper" : "Show paper"}
              </Button>
              <Tooltip title="More">
                <IconButton size="small" onClick={(e) => setMenuAnchor(e.currentTarget)} aria-label="More">
                  <MoreVertIcon />
                </IconButton>
              </Tooltip>
              <Menu anchorEl={menuAnchor} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}>
                <MenuItem onClick={clearChat} disabled={streaming || chat.turns.length === 0}>
                  <ListItemIcon>
                    <RestartAltIcon fontSize="small" />
                  </ListItemIcon>
                  Clear chat
                </MenuItem>
              </Menu>
            </Stack>
          )
        }
      >
        {!paper ? (
          <Stack sx={{ flex: 1, justifyContent: "center", alignItems: "center", px: 2 }}>
            <Box sx={{ width: "100%", maxWidth: 640 }}>
              <Typography variant="h4" sx={{ textAlign: "center", mb: 1, fontWeight: 600 }}>
                Read papers with Claude
              </Typography>
              <Typography color="text.secondary" sx={{ textAlign: "center", mb: 3 }}>
                Add a paper, then ask about it. Answers cite pages; click one to open the PDF there.
              </Typography>
              {errorAlert}
              {loaded && <DropZone onAdd={add} />}
            </Box>
          </Stack>
        ) : empty ? (
          <Stack sx={{ flex: 1, overflowY: "auto", justifyContent: "center", alignItems: "center", px: 2, py: 3 }}>
            <Box sx={{ width: "100%", maxWidth: CHAT_MAX_WIDTH }}>
              <Typography variant="h5" sx={{ textAlign: "center", fontWeight: 600 }}>
                {paper.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center", mt: 0.5, mb: 3 }}>
                {paper.pages} pages · {paper.filename} · ask anything about it
              </Typography>
              <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1, justifyContent: "center", mb: 2 }}>
                {STARTERS.map((s) => (
                  <Chip key={s} label={s} variant="outlined" onClick={() => send(s)} />
                ))}
              </Stack>
              {errorAlert}
              {composer(true)}
            </Box>
          </Stack>
        ) : (
          <>
            <Box sx={{ flex: 1, overflowY: "auto", px: { xs: 2, md: 4 } }}>
              <Box sx={{ maxWidth: CHAT_MAX_WIDTH, mx: "auto", py: 2 }}>
                {chat.turns.map((t, i) => (
                  <TurnItem key={t.id ?? `local-${i}`} turn={t} />
                ))}
                {chat.draft && <TurnItem turn={chat.draft} streaming />}
                <div ref={bottomRef} />
              </Box>
            </Box>
            <Box sx={{ px: { xs: 2, md: 4 }, pb: 2 }}>
              <Box sx={{ maxWidth: CHAT_MAX_WIDTH, mx: "auto" }}>
                {errorAlert}
                {composer(false)}
              </Box>
            </Box>
          </>
        )}
      </SplitLayout>

      {active && viewer.open && paper && (
        <PaperViewer
          paper={details[paper.id] ?? { ...paper, markdown: undefined }}
          pdfUrl={pdfUrl(paper.id)}
          view={viewer.view}
          onViewChange={(view) => setViewer((v) => ({ ...v, view }))}
          target={viewer}
          onClose={() => setViewer((v) => ({ ...v, open: false }))}
          onToast={setToast}
        />
      )}
      <Snackbar
        open={!!toast}
        autoHideDuration={2500}
        onClose={() => setToast(null)}
        message={toast}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </PageLinkContext.Provider>
  );
}
