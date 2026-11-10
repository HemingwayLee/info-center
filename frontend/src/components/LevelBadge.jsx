import { Box } from "@mui/material";
import { LEVEL_COLORS } from "../sources";

/** "Lv1".."Lv4" pill in the level's color; "Unrated" when level is null. */
export default function LevelBadge({ level, small = false }) {
  return (
    <Box
      component="span"
      sx={{
        display: "inline-block",
        px: small ? 0.6 : 1,
        py: small ? 0 : 0.25,
        borderRadius: 1,
        bgcolor: level ? LEVEL_COLORS[level] : "action.selected",
        color: level ? "#fff" : "text.secondary",
        fontWeight: 700,
        fontSize: small ? 11 : 13,
        lineHeight: 1.6,
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {level ? `Lv${level}` : "Unrated"}
    </Box>
  );
}
