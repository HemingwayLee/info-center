import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  InputAdornment,
  InputBase,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import SearchIcon from "@mui/icons-material/Search";
import { api } from "../api";
import LevelBadge from "../components/LevelBadge";
import { LEVEL_COLORS, levelTextSx } from "../sources";

function AddSource({ level, onAdd }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const name = value.trim();
    if (!name || busy) return;
    setBusy(true);
    try {
      await onAdd(name, level);
      setValue("");
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Paper
        variant="outlined"
        sx={{
          display: "inline-flex",
          alignItems: "center",
          pl: 1.25,
          borderStyle: "dashed",
          borderRadius: 4,
          borderColor: error ? "error.main" : "divider",
          maxWidth: "100%",
        }}
      >
        <InputBase
          placeholder="Add website or platform"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
          }}
          inputProps={{ "aria-label": `Add a source to Lv${level}`, maxLength: 200 }}
          sx={{ fontSize: 14, width: 210 }}
        />
        <IconButton size="small" onClick={submit} disabled={!value.trim() || busy} aria-label="Add">
          <AddIcon fontSize="small" />
        </IconButton>
      </Paper>
      {error && (
        <Typography variant="caption" color="error" sx={{ display: "block", mt: 0.5 }}>
          {error}
        </Typography>
      )}
    </Box>
  );
}

const cellSx = { display: { xs: "block", md: "table-cell" }, verticalAlign: "top" };

export default function SourcePage() {
  const [levels, setLevels] = useState([]);
  const [sources, setSources] = useState([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);
  const [menu, setMenu] = useState(null); // { anchor, source }
  const [dragOver, setDragOver] = useState(null);
  const [removed, setRemoved] = useState(null); // last removed source, for Undo

  useEffect(() => {
    Promise.all([api.sourceLevels(), api.listSources()])
      .then(([lv, src]) => {
        setLevels(lv);
        setSources(src);
      })
      .catch((e) => setError(`Cannot load sources: ${e.message}`));
  }, []);

  const byLevel = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const groups = Object.fromEntries(levels.map((l) => [l.level, []]));
    for (const s of sources) {
      if (!q || s.name.toLowerCase().includes(q)) groups[s.level]?.push(s);
    }
    return groups;
  }, [levels, sources, filter]);

  const add = async (name, level) => {
    const created = await api.createSource(name, level);
    setSources((prev) => [...prev, created]);
  };

  const move = async (source, level) => {
    setMenu(null);
    if (source.level === level) return;
    setSources((prev) => prev.map((s) => (s.id === source.id ? { ...s, level } : s)));
    try {
      await api.updateSource(source.id, { level });
    } catch (e) {
      setSources((prev) => prev.map((s) => (s.id === source.id ? source : s)));
      setError(`Couldn't move "${source.name}": ${e.message}`);
    }
  };

  const remove = async (source) => {
    setMenu(null);
    setSources((prev) => prev.filter((s) => s.id !== source.id));
    try {
      await api.deleteSource(source.id);
      setRemoved(source);
    } catch (e) {
      setSources((prev) => [...prev, source]);
      setError(`Couldn't remove "${source.name}": ${e.message}`);
    }
  };

  const undoRemove = async () => {
    const source = removed;
    setRemoved(null);
    try {
      await add(source.name, source.level);
    } catch (e) {
      setError(`Couldn't restore "${source.name}": ${e.message}`);
    }
  };

  const onDrop = (e, level) => {
    e.preventDefault();
    setDragOver(null);
    const id = Number(e.dataTransfer.getData("text/x-source-id"));
    const source = sources.find((s) => s.id === id);
    if (source) move(source, level);
  };

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
              Source credibility
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Drag a site to another level, or click it to move or remove it.
            </Typography>
          </Box>
          <TextField
            size="small"
            placeholder="Filter sites"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" />
                  </InputAdornment>
                ),
              },
            }}
            sx={{ width: { xs: "100%", sm: 240 } }}
          />
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <TableContainer component={Paper} variant="outlined">
          <Table sx={{ display: { xs: "block", md: "table" } }}>
            <TableHead sx={{ display: { xs: "none", md: "table-header-group" } }}>
              <TableRow>
                <TableCell sx={{ width: 320, fontWeight: 600 }}>Level</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Websites &amp; platforms</TableCell>
              </TableRow>
            </TableHead>
            <TableBody sx={{ display: { xs: "block", md: "table-row-group" } }}>
              {levels.map(({ level, name, description }) => {
                const color = LEVEL_COLORS[level];
                const items = byLevel[level] ?? [];
                return (
                  <TableRow
                    key={level}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragOver(level);
                    }}
                    onDragLeave={(e) => {
                      if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(null);
                    }}
                    onDrop={(e) => onDrop(e, level)}
                    sx={{
                      display: { xs: "block", md: "table-row" },
                      boxShadow: `inset 5px 0 0 ${color}`,
                      bgcolor: dragOver === level ? alpha(color, 0.1) : "transparent",
                      transition: "background-color 120ms",
                      "&:last-child td": { borderBottom: { md: 0 } },
                    }}
                  >
                    <TableCell sx={{ ...cellSx, pl: 3, borderBottom: { xs: 0, md: 1 }, borderColor: { md: "divider" } }}>
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 0.75 }}>
                        <LevelBadge level={level} />
                        <Typography sx={[{ fontWeight: 600 }, levelTextSx(level)]}>{name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {items.length}
                        </Typography>
                      </Stack>
                      <Typography variant="body2" color="text.secondary">
                        {description}
                      </Typography>
                    </TableCell>
                    <TableCell sx={{ ...cellSx, pl: { xs: 3, md: 2 } }}>
                      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, alignItems: "flex-start" }}>
                        {items.map((s) => (
                          <Chip
                            key={s.id}
                            label={s.name}
                            size="small"
                            variant="outlined"
                            draggable
                            onDragStart={(e) => {
                              e.dataTransfer.setData("text/x-source-id", String(s.id));
                              e.dataTransfer.effectAllowed = "move";
                            }}
                            onDragEnd={() => setDragOver(null)}
                            onClick={(e) => setMenu({ anchor: e.currentTarget, source: s })}
                            onDelete={() => remove(s)}
                            sx={{
                              bgcolor: alpha(color, 0.12),
                              borderColor: alpha(color, 0.55),
                              cursor: "grab",
                              fontSize: 13,
                              "& .MuiChip-deleteIcon": { color: alpha(color, 0.7), "&:hover": { color } },
                            }}
                          />
                        ))}
                        {filter && items.length === 0 && (
                          <Typography variant="body2" color="text.disabled" sx={{ py: 0.25 }}>
                            No matches
                          </Typography>
                        )}
                      </Box>
                      <Box sx={{ mt: 1.5 }}>
                        <AddSource level={level} onAdd={add} />
                      </Box>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      <Menu anchorEl={menu?.anchor} open={Boolean(menu)} onClose={() => setMenu(null)}>
        <ListSubheader sx={{ lineHeight: "32px" }}>Move “{menu?.source.name}” to</ListSubheader>
        {levels.map(({ level, name }) => (
          <MenuItem
            key={level}
            disabled={menu?.source.level === level}
            onClick={() => move(menu.source, level)}
            dense
          >
            <ListItemIcon>
              <LevelBadge level={level} />
            </ListItemIcon>
            <ListItemText sx={{ ml: 1 }}>{name}</ListItemText>
          </MenuItem>
        ))}
        <Divider />
        <MenuItem dense onClick={() => remove(menu.source)} sx={{ color: "error.main" }}>
          <ListItemIcon>
            <DeleteOutlineIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Remove</ListItemText>
        </MenuItem>
      </Menu>

      <Snackbar
        open={Boolean(removed)}
        autoHideDuration={5000}
        onClose={(_, reason) => reason !== "clickaway" && setRemoved(null)}
        message={removed ? `Removed “${removed.name}”` : ""}
        action={
          <Button color="primary" size="small" onClick={undoRemove}>
            Undo
          </Button>
        }
      />
    </Box>
  );
}
