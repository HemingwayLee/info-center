import { useRef, useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { TitleEditor } from "./Sidebar";

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/**
 * The paper list: add PDFs (button or drop), and select, rename or delete a paper. `uploads` are files still
 * being converted ({key, name}).
 */
export default function PaperSidebar({ papers, uploads, currentId, onSelect, onAdd, onRename, onDelete }) {
  const inputRef = useRef(null);
  const [editingId, setEditingId] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [confirm, setConfirm] = useState(null); // paper to delete

  return (
    <Stack
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget) && setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        onAdd([...(e.dataTransfer.files ?? [])]);
      }}
      sx={{
        height: "100%",
        p: 1.5,
        outline: dragging ? 2 : 0,
        outlineColor: "primary.main",
        outlineOffset: -4,
        bgcolor: (t) => (dragging ? alpha(t.palette.primary.main, 0.06) : "transparent"),
      }}
    >
      <Button
        variant="outlined"
        startIcon={<UploadFileIcon />}
        // On phones the side panel is a drawer that closes on any click; keep it open for the file picker.
        onClick={(e) => {
          e.stopPropagation();
          inputRef.current?.click();
        }}
        sx={{ mb: 1 }}
      >
        Add paper (PDF)
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        onChange={(e) => {
          onAdd([...(e.target.files ?? [])]);
          e.target.value = ""; // allow picking the same file again
        }}
      />

      <Box sx={{ flex: 1, overflowY: "auto", mx: -0.5 }}>
        <List dense>
          {uploads.map((u) => (
            <ListItemButton key={u.key} disabled sx={{ borderRadius: 1, gap: 1 }}>
              <CircularProgress size={16} />
              <ListItemText
                primary={u.name}
                secondary="Converting…"
                slotProps={{ primary: { noWrap: true }, secondary: { fontSize: 12 } }}
              />
            </ListItemButton>
          ))}
          {papers.map((p) => {
            const editing = p.id === editingId;
            const active = p.id === currentId;
            return (
              <ListItemButton
                key={p.id}
                selected={active}
                onClick={(e) => (editing ? e.stopPropagation() : onSelect(p.id))}
                onDoubleClick={() => setEditingId(p.id)}
                disableRipple={editing}
                sx={{
                  borderRadius: 1,
                  gap: 0.25,
                  alignItems: "flex-start",
                  "&:hover .actions, &:focus-within .actions": { visibility: "visible" },
                }}
              >
                {editing ? (
                  <TitleEditor
                    initial={p.title}
                    label="Paper title"
                    onSave={(title) => {
                      setEditingId(null);
                      onRename(p.id, title);
                    }}
                    onCancel={() => setEditingId(null)}
                  />
                ) : (
                  <>
                    <ListItemText
                      primary={p.title}
                      secondary={`${plural(p.pages, "page")} · ${plural(p.questions, "question")}`}
                      title={`${p.title}\n${p.filename}`}
                      slotProps={{
                        // Paper titles are long: two lines, then an ellipsis.
                        primary: {
                          sx: { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" },
                        },
                        secondary: { noWrap: true, fontSize: 12 },
                      }}
                    />
                    <Box
                      className="actions"
                      sx={{ display: "flex", flexShrink: 0, visibility: active ? "visible" : "hidden" }}
                    >
                      <Tooltip title="Rename">
                        <IconButton
                          size="small"
                          aria-label="Rename paper"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingId(p.id);
                          }}
                        >
                          <EditOutlinedIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          aria-label="Delete paper"
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirm(p);
                          }}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </>
                )}
              </ListItemButton>
            );
          })}
        </List>
        {papers.length === 0 && uploads.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ px: 1 }}>
            No papers yet. Add a PDF, or drop one here.
          </Typography>
        )}
      </Box>

      <Dialog open={!!confirm} onClose={() => setConfirm(null)} onClick={(e) => e.stopPropagation()}>
        <DialogTitle>Delete this paper?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            &ldquo;{confirm?.title}&rdquo; is removed with its PDF, its Markdown and its chat. This can&apos;t be
            undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => {
              onDelete(confirm.id);
              setConfirm(null);
            }}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
