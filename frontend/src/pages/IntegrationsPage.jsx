import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  FormGroup,
  FormHelperText,
  IconButton,
  Link,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CheckIcon from "@mui/icons-material/Check";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import KeyIcon from "@mui/icons-material/Key";
import { api } from "../api";

const SCOPES = [
  { id: "research", label: "Research", help: "Start and cancel research" },
  { id: "read", label: "Read", help: "Get results and search past answers" },
];

const mono = { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 13 };

function CopyText({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked (e.g. not HTTPS): the text is still selectable.
    }
  };
  return (
    <Tooltip title={copied ? "Copied" : label}>
      <IconButton size="small" onClick={copy} aria-label={label}>
        {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
      </IconButton>
    </Tooltip>
  );
}

/** A line of copyable monospace text. */
function CodeLine({ children, label }) {
  return (
    <Paper
      variant="outlined"
      sx={{ display: "flex", alignItems: "flex-start", gap: 1, pl: 1.5, pr: 0.5, py: 0.5, bgcolor: "action.hover" }}
    >
      <Box component="code" sx={{ ...mono, flex: 1, py: 0.5, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
        {children}
      </Box>
      <CopyText text={children} label={label} />
    </Paper>
  );
}

const claudeCommand = (mcpUrl, key) =>
  `claude mcp add --transport http info-center ${mcpUrl} --header "Authorization: Bearer ${key}"`;

const mcpJson = (mcpUrl, key) =>
  JSON.stringify(
    { mcpServers: { "info-center": { type: "http", url: mcpUrl, headers: { Authorization: `Bearer ${key}` } } } },
    null,
    2
  );

function ConnectionInfo({ info }) {
  if (!info) return null;
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        How other systems connect
      </Typography>
      <Stack spacing={1.5}>
        <Box>
          <Typography variant="body2" sx={{ mb: 0.5 }}>
            <b>MCP</b> (for AI agents): Streamable HTTP, with the integration&apos;s key in every request.
          </Typography>
          <CodeLine label="Copy MCP URL">{info.mcp_url}</CodeLine>
        </Box>
        <Box>
          <Typography variant="body2" sx={{ mb: 0.5 }}>
            <b>REST API</b>: start research, then poll for the result.{" "}
            <Link href="/api/v1/docs" target="_blank" rel="noopener noreferrer">
              API docs
            </Link>
          </Typography>
          <CodeLine label="Copy API URL">{info.api_url}</CodeLine>
        </Box>
        <Typography variant="body2" color="text.secondary">
          Authenticate with <Box component="code" sx={mono}>{info.auth}</Box>. Questions from integrations can only
          use {info.allowed_tools.join(" and ")}: no shell commands or file access.
        </Typography>
      </Stack>
    </Paper>
  );
}

/** Create or edit an integration's name, permissions and daily limit. */
function IntegrationForm({ open, initial, onClose, onSave }) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["research", "read"]);
  const [limit, setLimit] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(initial?.name ?? "");
    setScopes(initial?.scopes ?? ["research", "read"]);
    setLimit(initial?.daily_limit ? String(initial.daily_limit) : "");
    setError(null);
  }, [open, initial]);

  const limitValue = limit.trim() === "" ? null : Number(limit);
  const limitInvalid = limitValue !== null && !(Number.isInteger(limitValue) && limitValue >= 1);
  const invalid = !name.trim() || scopes.length === 0 || limitInvalid;

  const save = async () => {
    if (invalid || busy) return;
    setBusy(true);
    try {
      await onSave({ name: name.trim(), scopes, daily_limit: limitValue });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id) => setScopes((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{initial ? "Edit integration" : "New integration"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            label="Name"
            placeholder="e.g. Market research agent"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            slotProps={{ htmlInput: { maxLength: 100 } }}
          />
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              Permissions
            </Typography>
            <FormGroup>
              {SCOPES.map((s) => (
                <FormControlLabel
                  key={s.id}
                  control={<Checkbox checked={scopes.includes(s.id)} onChange={() => toggle(s.id)} />}
                  label={
                    <span>
                      {s.label}{" "}
                      <Typography component="span" variant="body2" color="text.secondary">
                        · {s.help}
                      </Typography>
                    </span>
                  }
                />
              ))}
            </FormGroup>
            {scopes.length === 0 && <FormHelperText error>Pick at least one permission.</FormHelperText>}
          </Box>
          <TextField
            label="Daily limit"
            placeholder="Unlimited"
            helperText={limitInvalid ? "A whole number, 1 or more" : "Questions per 24 hours; empty means unlimited"}
            error={limitInvalid}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            slotProps={{ htmlInput: { inputMode: "numeric" } }}
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={invalid || busy}>
          {initial ? "Save" : "Create"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** Shows a new API key once, with ready-to-paste setup for MCP clients. */
function KeyDialog({ created, info, onClose }) {
  if (!created) return null;
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>API key for {created.name}</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 2 }}>
          Copy it now: this is the only time it&apos;s shown. If it&apos;s lost, create a new key.
        </Alert>
        <CodeLine label="Copy API key">{created.api_key}</CodeLine>
        {info && (
          <Stack spacing={1} sx={{ mt: 2 }}>
            <Typography variant="body2">
              <b>Claude Code</b>: add it as an MCP server
            </Typography>
            <CodeLine label="Copy command">{claudeCommand(info.mcp_url, created.api_key)}</CodeLine>
            <Typography variant="body2">
              <b>Other MCP clients</b>: JSON config
            </Typography>
            <CodeLine label="Copy JSON">{mcpJson(info.mcp_url, created.api_key)}</CodeLine>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button variant="contained" onClick={onClose}>
          Done
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function Confirm({ confirm, onClose }) {
  if (!confirm) return null;
  return (
    <Dialog open onClose={onClose}>
      <DialogTitle>{confirm.title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{confirm.text}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          color="error"
          variant="contained"
          onClick={async () => {
            onClose();
            await confirm.run();
          }}
        >
          {confirm.action}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : "Never");

export default function IntegrationsPage() {
  const [items, setItems] = useState([]);
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null); // null | { initial: integration | null }
  const [created, setCreated] = useState(null); // integration with its new api_key, shown once
  const [confirm, setConfirm] = useState(null);

  const load = useCallback(async () => {
    try {
      setItems(await api.listIntegrations());
    } catch (e) {
      setError(`Cannot load integrations: ${e.message}`);
    }
  }, []);

  useEffect(() => {
    load();
    api
      .integrationConnection()
      .then(setInfo)
      .catch(() => {});
  }, [load]);

  const replace = (updated) => setItems((list) => list.map((i) => (i.id === updated.id ? updated : i)));

  const save = async (data) => {
    if (form.initial) {
      replace(await api.updateIntegration(form.initial.id, data));
    } else {
      const made = await api.createIntegration(data);
      setItems((list) => [...list, made]);
      setCreated(made);
    }
    setForm(null);
  };

  const setEnabled = async (item, enabled) => {
    replace({ ...item, enabled });
    try {
      replace(await api.updateIntegration(item.id, { enabled }));
    } catch (e) {
      replace(item);
      setError(`Couldn't update "${item.name}": ${e.message}`);
    }
  };

  const rotate = (item) =>
    setConfirm({
      title: `New key for "${item.name}"?`,
      text: "The current key stops working right away. Anything using it must switch to the new key.",
      action: "Create new key",
      run: async () => {
        try {
          const made = await api.rotateIntegrationKey(item.id);
          replace(made);
          setCreated(made);
        } catch (e) {
          setError(`Couldn't create a new key: ${e.message}`);
        }
      },
    });

  const remove = (item) =>
    setConfirm({
      title: `Delete "${item.name}"?`,
      text: "Its key stops working right away. Its conversations are kept, as ordinary chats.",
      action: "Delete",
      run: async () => {
        try {
          await api.deleteIntegration(item.id);
          setItems((list) => list.filter((i) => i.id !== item.id));
        } catch (e) {
          setError(`Couldn't delete "${item.name}": ${e.message}`);
        }
      },
    });

  return (
    <Box sx={{ flex: 1, overflowY: "auto", px: 2, py: 3 }}>
      <Box sx={{ maxWidth: 1100, mx: "auto" }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={2}
          sx={{ justifyContent: "space-between", alignItems: { sm: "flex-end" }, mb: 2 }}
        >
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Integrations
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Other systems that can use this app for research, through MCP or the REST API. Turn one off to cut it
              off at once.
            </Typography>
          </Box>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setForm({ initial: null })}>
            New integration
          </Button>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <ConnectionInfo info={info} />

        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>On</TableCell>
                <TableCell>Name</TableCell>
                <TableCell>Key</TableCell>
                <TableCell>Permissions</TableCell>
                <TableCell>Daily limit</TableCell>
                <TableCell>Questions</TableCell>
                <TableCell>Last used</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} sx={{ opacity: item.enabled ? 1 : 0.6 }}>
                  <TableCell padding="checkbox">
                    <Switch
                      size="small"
                      checked={item.enabled}
                      onChange={(e) => setEnabled(item, e.target.checked)}
                      slotProps={{ input: { "aria-label": `${item.name} enabled` } }}
                    />
                  </TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>{item.name}</TableCell>
                  <TableCell>
                    <Box component="code" sx={mono}>
                      {item.key_prefix}…
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
                      {item.scopes.map((s) => (
                        <Chip key={s} size="small" label={SCOPES.find((x) => x.id === s)?.label ?? s} />
                      ))}
                    </Stack>
                  </TableCell>
                  <TableCell>{item.daily_limit ?? "Unlimited"}</TableCell>
                  <TableCell>
                    <Tooltip
                      title={
                        item.cost_usd_total != null ? `Estimated cost: $${item.cost_usd_total.toFixed(2)}` : ""
                      }
                    >
                      <span>
                        {item.questions_24h} today · {item.questions_total} total
                      </span>
                    </Tooltip>
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{formatDate(item.last_used_at)}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <Tooltip title="Edit">
                      <IconButton size="small" onClick={() => setForm({ initial: item })} aria-label="Edit">
                        <EditOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="New key">
                      <IconButton size="small" onClick={() => rotate(item)} aria-label="Create a new key">
                        <KeyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton size="small" onClick={() => remove(item)} aria-label="Delete">
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8}>
                    <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
                      No integrations yet. Create one to give another system an API key.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      <IntegrationForm
        open={form !== null}
        initial={form?.initial ?? null}
        onClose={() => setForm(null)}
        onSave={save}
      />
      <KeyDialog created={created} info={info} onClose={() => setCreated(null)} />
      <Confirm confirm={confirm} onClose={() => setConfirm(null)} />
    </Box>
  );
}
