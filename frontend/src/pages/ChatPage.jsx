import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, MenuItem, Select, Stack, Typography } from "@mui/material";
import { api, applyEvent, newTurn, streamMessage } from "../api";
import Composer from "../components/Composer";
import TurnItem from "../components/TurnItem";
import Sidebar from "../components/Sidebar";
import SplitLayout from "../layout/SplitLayout";
import { SourcesContext } from "../sources";

// Width of the message column and composer.
const CHAT_MAX_WIDTH = 1200;
const RESEARCH_KEY = "refMode";

function readResearch() {
  try {
    return localStorage.getItem(RESEARCH_KEY) === "true";
  } catch {
    return false;
  }
}

export default function ChatPage({ active = true }) {
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [conversations, setConversations] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [turns, setTurns] = useState([]); // saved questions and answers in this chat
  const [draft, setDraft] = useState(null); // turn being answered right now
  const [error, setError] = useState(null);
  const [sources, setSources] = useState([]); // credibility levels for coloring cited text
  const [promptHistory, setPromptHistory] = useState([]); // sent prompts, newest first (Up/Down recall)
  const [research, setResearch] = useState(readResearch); // "Ref" toggle, remembered per browser

  const changeResearch = (on) => {
    setResearch(on);
    try {
      localStorage.setItem(RESEARCH_KEY, String(on));
    } catch {
      // Storage unavailable: the toggle still works, it just isn't remembered.
    }
  };

  const abortRef = useRef(null);
  const bottomRef = useRef(null);
  const streaming = draft !== null;

  const refreshConversations = useCallback(async () => {
    setConversations(await api.listConversations());
  }, []);

  useEffect(() => {
    api
      .models()
      .then(({ models, default: def }) => {
        setModels(models);
        setModel(def);
      })
      .catch((e) => setError(`Cannot reach the API: ${e.message}`));
    refreshConversations().catch(() => {});
    api
      .promptHistory()
      .then(setPromptHistory)
      .catch(() => {});
  }, [refreshConversations]);

  // Reload whenever the tab is shown, so edits on the Source tab recolor answers right away.
  useEffect(() => {
    if (active)
      api
        .listSources()
        .then(setSources)
        .catch(() => {});
  }, [active]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [turns, draft]);

  const openConversation = async (id) => {
    if (streaming) return;
    setCurrentId(id);
    try {
      const convo = await api.getConversation(id);
      setTurns(convo.turns);
      setModel(convo.model);
    } catch (e) {
      setError(e.message);
    }
  };

  const newChat = () => {
    if (streaming) return;
    setCurrentId(null);
    setTurns([]);
  };

  const renameChat = async (id, title) => {
    // Show the new title right away; roll back if the save fails.
    const previous = conversations;
    setConversations((list) => list.map((c) => (c.id === id ? { ...c, title } : c)));
    try {
      await api.updateConversation(id, { title });
    } catch (e) {
      setConversations(previous);
      setError(`Couldn't rename the conversation: ${e.message}`);
    }
  };

  const deleteChat = async (id) => {
    await api.deleteConversation(id);
    if (id === currentId) newChat();
    refreshConversations();
  };

  const changeModel = async (value) => {
    setModel(value);
    if (currentId) await api.updateConversation(currentId, { model: value });
  };

  const send = async (text) => {
    setError(null);
    let id = currentId;
    try {
      if (!id) {
        id = (await api.createConversation(model)).id;
        setCurrentId(id);
      }
    } catch (e) {
      setError(e.message);
      return;
    }

    setPromptHistory((prev) => (prev[0] === text ? prev : [text, ...prev]));
    let final = newTurn(text, { research, model });
    setDraft(final);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamMessage(id, text, {
        research,
        signal: controller.signal,
        onEvent: (event) => {
          final = applyEvent(final, event);
          setDraft(final);
        },
      });
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
    } finally {
      abortRef.current = null;
      // The server's saved copy if it arrived; after Stop, the partial local one (saved on the server too,
      // and shown from there next time the chat is opened).
      setTurns((prev) => [...prev, final.status === "running" ? { ...final, status: "stopped" } : final]);
      setDraft(null);
      refreshConversations();
    }
  };

  const stop = () => abortRef.current?.abort();

  const empty = turns.length === 0 && !streaming;

  return (
    <SourcesContext.Provider value={sources}>
      <SplitLayout
        sidebar={
          <Sidebar
            conversations={conversations}
            currentId={currentId}
            onSelect={openConversation}
            onNew={newChat}
            onDelete={deleteChat}
            onRename={renameChat}
          />
        }
        header={
          <Select
            size="small"
            variant="standard"
            disableUnderline
            value={models.length ? model : ""}
            onChange={(e) => changeModel(e.target.value)}
            disabled={streaming}
            sx={{ fontWeight: 600 }}
          >
            {models.map((m) => (
              <MenuItem key={m.id} value={m.id}>
                {m.name}
              </MenuItem>
            ))}
          </Select>
        }
      >
        {empty ? (
          <Stack
            sx={{
              flex: 1,
              justifyContent: "center",
              alignItems: "center",
              px: 2,
            }}
          >
            <Box sx={{ width: "100%", maxWidth: CHAT_MAX_WIDTH }}>
              <Typography
                variant="h4"
                sx={{ textAlign: "center", mb: 3, fontWeight: 600 }}
              >
                What can Claude Code do for you?
              </Typography>
              {error && (
                <Alert
                  severity="error"
                  sx={{ mb: 2 }}
                  onClose={() => setError(null)}
                >
                  {error}
                </Alert>
              )}
              <Composer
                onSend={send}
                onStop={stop}
                streaming={streaming}
                history={promptHistory}
                research={research}
                onResearchChange={changeResearch}
                autoFocus
              />
            </Box>
          </Stack>
        ) : (
          <>
            <Box sx={{ flex: 1, overflowY: "auto", px: { xs: 2, md: 4 } }}>
              <Box sx={{ maxWidth: CHAT_MAX_WIDTH, mx: "auto", py: 2 }}>
                {turns.map((t, i) => (
                  <TurnItem key={t.id ?? `local-${i}`} turn={t} />
                ))}
                {draft && <TurnItem turn={draft} streaming />}
                <div ref={bottomRef} />
              </Box>
            </Box>
            <Box sx={{ px: { xs: 2, md: 4 }, pb: 2 }}>
              <Box sx={{ maxWidth: CHAT_MAX_WIDTH, mx: "auto" }}>
                {error && (
                  <Alert
                    severity="error"
                    sx={{ mb: 1 }}
                    onClose={() => setError(null)}
                  >
                    {error}
                  </Alert>
                )}
                <Composer
                  onSend={send}
                  onStop={stop}
                  streaming={streaming}
                  history={promptHistory}
                research={research}
                onResearchChange={changeResearch}
                />
              </Box>
            </Box>
          </>
        )}
      </SplitLayout>
    </SourcesContext.Provider>
  );
}
