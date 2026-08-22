import { lazy } from "react";
import { Routes, Route, Navigate, useParams } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import Home from "./pages/home";

// Route-level code splitting. The shell (AppLayout) and the landing page
// (Home) load eagerly so the app paints immediately on launch; every other
// page is its own lazy chunk, pulled in on first navigation. AppLayout
// wraps <Outlet> in <Suspense>, so the sidebar/header stay put while a
// page chunk loads.
const ColonyChat = lazy(() => import("./pages/colony-chat"));
const QueenDM = lazy(() => import("./pages/queen-dm"));
const OrgChart = lazy(() => import("./pages/org-chart"));
const PromptLibrary = lazy(() => import("./pages/prompt-library"));
const SkillsLibrary = lazy(() => import("./pages/skills-library"));
const MemoryLibrary = lazy(() => import("./pages/memory-library"));
const CredentialsPage = lazy(() => import("./pages/credentials"));
const NotFound = lazy(() => import("./pages/not-found"));

// Keying ColonyChat on the route param makes colony identity the component's
// identity: switching colonies unmounts the old page instead of reusing its
// instance. Without this, React keeps one ColonyChat alive across the whole
// /colony/* space and the page's own reset is gated on `agentPath`, which is
// empty for any colony not yet in the cached colony list (every freshly created
// one). That left the previous colony's transcript, sessionId and live SSE
// stream bound under the new colony's URL until the 30s colony poll caught up.
function ColonyChatRoute() {
  const { colonyId } = useParams<{ colonyId: string }>();
  return <ColonyChat key={colonyId} />;
}

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/colony/:colonyId" element={<ColonyChatRoute />} />
        {/* /queen-routing (LLM-classified queen pick) is deprecated: starting
            a conversation requires hand-picking a queen on Home. Stale links
            land on Home instead of a dead classifier screen. */}
        <Route path="/queen-routing" element={<Navigate to="/" replace />} />
        <Route path="/queen/:queenId" element={<QueenDM />} />
        <Route path="/org-chart" element={<OrgChart />} />
        <Route path="/skills-library" element={<SkillsLibrary />} />
        <Route path="/prompt-library" element={<PromptLibrary />} />
        {/* Tools were demoted into the Skills page as the "MCP Tools" tab.
            Keep the old path working (bookmarks, stale transcript links). */}
        <Route
          path="/tool-library"
          element={<Navigate to="/skills-library?tab=mcp" replace />}
        />
        <Route path="/memory-library" element={<MemoryLibrary />} />
        <Route path="/credentials" element={<CredentialsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export default App;
