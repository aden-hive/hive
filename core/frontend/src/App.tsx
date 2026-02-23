import { Routes, Route } from "react-router-dom";
import Home from "./pages/home";
import MyAgents from "./pages/my-agents";
import Dashboard from "./pages/dashboard";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/my-agents" element={<MyAgents />} />
      <Route path="/dashboard" element={<Dashboard />} />
    </Routes>
  );
}

export default App;
