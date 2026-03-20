import { Routes, Route } from "react-router-dom";
import Home from "./pages/home";
import MyAgents from "./pages/my-agents";
import Workspace from "./pages/workspace";
import Dashboard from "./pages/dashboard";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/my-agents" element={<MyAgents />} />
      <Route path="/workspace" element={<Workspace />} />
    </Routes>
  );
}

export default App;
