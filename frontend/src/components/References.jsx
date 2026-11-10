import { Box, Link, Stack, Typography } from "@mui/material";
import LevelBadge from "./LevelBadge";

export default function References({ refs }) {
  return (
    <Box sx={{ mt: 2, pt: 1.5, borderTop: 1, borderColor: "divider" }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.75 }}>
        References
      </Typography>
      <Stack component="ol" spacing={0.75} sx={{ listStyle: "none", m: 0, p: 0 }}>
        {refs.map((r) => (
          <Stack
            key={r.n}
            component="li"
            direction="row"
            spacing={1}
            sx={{ alignItems: "baseline", fontSize: 14, minWidth: 0 }}
          >
            <Typography component="span" variant="body2" color="text.secondary" sx={{ minWidth: 24 }}>
              [{r.n}]
            </Typography>
            <LevelBadge level={r.level} small />
            <Box sx={{ minWidth: 0, wordBreak: "break-word" }}>
              <Link href={r.url} target="_blank" rel="noopener noreferrer" underline="hover">
                {r.title}
              </Link>
              {r.publisher && (
                <Typography component="span" variant="body2" color="text.secondary">
                  {" "}
                  · {r.publisher}
                </Typography>
              )}
              {r.host && (
                <Typography component="span" variant="body2" color="text.secondary">
                  {" "}
                  · {r.host}
                  {r.source && r.source.name.toLowerCase() !== r.host ? ` (${r.source.name})` : ""}
                </Typography>
              )}
            </Box>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}
