import { Routes, Route } from "react-router-dom";
import Home from "./pages/home";
import MyAgents from "./pages/my-agents";
import Workspace from "./pages/workspace";
import AppShell from "./components/AppShell";

function App() {
  return (
    <Routes>
      <Route path="/" element={<AppShell><Home /></AppShell>} />
      <Route path="/my-agents" element={<AppShell><MyAgents /></AppShell>} />
      <Route path="/workspace" element={<Workspace />} />
    </Routes>
  );
}

export default App;
