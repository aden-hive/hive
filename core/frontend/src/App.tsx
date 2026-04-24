import { Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import Home from "./pages/home";
import ColonyChat from "./pages/colony-chat";
import QueenDM from "./pages/queen-dm";
import OrgChart from "./pages/org-chart";
import PromptLibrary from "./pages/prompt-library";
import SkillsLibrary from "./pages/skills-library";
import ToolLibrary from "./pages/tool-library";
import CredentialsPage from "./pages/credentials";
import NotFound from "./pages/not-found";

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/colony/:colonyId" element={<ColonyChat />} />
        <Route path="/queen/:queenId" element={<QueenDM />} />
        <Route path="/org-chart" element={<OrgChart />} />
        <Route path="/skills-library" element={<SkillsLibrary />} />
        <Route path="/prompt-library" element={<PromptLibrary />} />
        <Route path="/tool-library" element={<ToolLibrary />} />
        <Route path="/credentials" element={<CredentialsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export default App;
