import { useMemo, useState } from "react";
import { Alert, Box, Button, Stack, Tooltip, Typography } from "@mui/material";
import CheckIcon from "@mui/icons-material/Check";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import FileDownloadOutlinedIcon from "@mui/icons-material/FileDownloadOutlined";
import MenuBookOutlinedIcon from "@mui/icons-material/MenuBookOutlined";
import { copyTurnForLLM, turnExportUrl } from "../api";
import { splitReferences } from "../citations";
import { hostnameOf, matchSource, useSources } from "../sources";
import Markdown from "./Markdown";
import References from "./References";
import ToolCall from "./ToolCall";

/**
 * The answer body and its references, each resolved to a credibility level from the current Source list.
 * Saved turns have structured references; while streaming they're still a section at the end of the text.
 */
function useAnswer(turn, sources) {
  return useMemo(() => {
    const { body, refs: list } =
      turn.id != null ? { body: turn.content, refs: turn.references } : splitReferences(turn.content);
    const refs = new Map();
    for (const r of list) {
      const source = matchSource(r.url, sources);
      refs.set(r.n, { ...r, host: hostnameOf(r.url), source, level: source?.level ?? null });
    }
    return { body, refs };
  }, [turn, sources]);
}

function Question({ text, research }) {
  return (
    <Stack sx={{ alignItems: "flex-end", my: 2 }}>
      <Box
        sx={{
          maxWidth: "80%",
          bgcolor: "action.selected",
          px: 2,
          py: 1.25,
          borderRadius: 3,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {text}
      </Box>
      {research && (
        <Typography
          variant="caption"
          color="text.secondary"
          title="Sent with Ref on: answered with cited sources"
          sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, mt: 0.5, mr: 1 }}
        >
          <MenuBookOutlinedIcon sx={{ fontSize: 14 }} />
          Ref
        </Typography>
      )}
    </Stack>
  );
}

function ExportActions({ turnId }) {
  const [copied, setCopied] = useState(null); // null | "ok" | error message

  const copy = async () => {
    try {
      await copyTurnForLLM(turnId);
      setCopied("ok");
    } catch (e) {
      setCopied(`Couldn't copy: ${e.message}`);
    }
    setTimeout(() => setCopied(null), 2000);
  };

  const buttonSx = { color: "text.secondary", textTransform: "none", minWidth: 0, px: 1 };
  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
      <Tooltip title="Copy question, answer and references as Markdown, ready to paste into another LLM">
        <Button
          size="small"
          onClick={copy}
          startIcon={copied === "ok" ? <CheckIcon /> : <ContentCopyIcon />}
          sx={buttonSx}
        >
          {copied === "ok" ? "Copied" : "Copy for LLM"}
        </Button>
      </Tooltip>
      <Tooltip title="Download this answer as JSON (question, answer, references, sources consulted)">
        <Button
          size="small"
          component="a"
          href={turnExportUrl(turnId, { download: true })}
          download
          startIcon={<FileDownloadOutlinedIcon />}
          sx={buttonSx}
        >
          Export
        </Button>
      </Tooltip>
      {copied && copied !== "ok" && (
        <Typography variant="caption" color="error">
          {copied}
        </Typography>
      )}
    </Stack>
  );
}

export default function TurnItem({ turn, streaming = false }) {
  const sources = useSources();
  const { body, refs } = useAnswer(turn, sources);
  const results = Object.fromEntries(
    turn.activity.filter((b) => b.type === "tool_result").map((b) => [b.tool_use_id, b])
  );
  const tools = turn.activity.filter((b) => b.type === "tool_use");

  return (
    <>
      <Question text={turn.question} research={turn.mode === "research"} />
      <Box sx={{ my: 2 }}>
        {tools.map((tool) => (
          <ToolCall key={tool.id} tool={tool} result={results[tool.id]} running={streaming} />
        ))}
        {body && <Markdown refs={refs}>{body}</Markdown>}
        {streaming && !body && tools.length === 0 && <Typography color="text.secondary">Thinking…</Typography>}
        {turn.error && (
          <Alert severity="error" sx={{ my: 1, whiteSpace: "pre-wrap" }}>
            {turn.error}
          </Alert>
        )}
        {turn.status === "stopped" && !streaming && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            Stopped
          </Typography>
        )}
        {refs.size > 0 && <References refs={[...refs.values()].sort((a, b) => a.n - b.n)} />}
        {!streaming && (
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", mt: 1, ml: -1 }}>
            {turn.id != null && <ExportActions turnId={turn.id} />}
            {turn.cost_usd != null && (
              <Typography variant="caption" color="text.disabled">
                ${turn.cost_usd.toFixed(4)}
              </Typography>
            )}
          </Stack>
        )}
      </Box>
    </>
  );
}
