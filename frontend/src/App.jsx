import { AppBar, Box, Tab, Tabs, Toolbar, Typography } from "@mui/material";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import ThemeToggle from "./components/ThemeToggle";
import ChatPage from "./pages/ChatPage";
import SourcePage from "./pages/SourcePage";

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const section = location.pathname.startsWith("/source") ? "source" : "chat";

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100dvh" }}>
      <AppBar position="static" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Toolbar variant="dense" sx={{ gap: 2 }}>
          <Typography variant="h6" sx={{ fontWeight: 700, display: { xs: "none", sm: "block" } }}>
            info-center
          </Typography>
          <Tabs
            value={section}
            onChange={(_, v) => navigate(`/${v}`)}
            sx={{ flex: 1, minHeight: 48, "& .MuiTab-root": { minHeight: 48 } }}
          >
            <Tab value="chat" label="Chat" />
            <Tab value="source" label="Source" />
          </Tabs>
          <ThemeToggle />
        </Toolbar>
      </AppBar>

      {/* Chat stays mounted while hidden so a streaming reply isn't interrupted by switching tabs. */}
      <Box sx={{ display: section === "chat" ? "flex" : "none", flex: 1, minHeight: 0 }}>
        <ChatPage active={section === "chat"} />
      </Box>

      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={null} />
        <Route path="/source" element={<SourcePage />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </Box>
  );
}
