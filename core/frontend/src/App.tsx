import { Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./components/ThemeProvider";
import Home from "./pages/home";
import MyAgents from "./pages/my-agents";
import Workspace from "./pages/workspace";

function App() {
  return (
    <ThemeProvider>
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/my-agents" element={<MyAgents />} />
      <Route path="/workspace" element={<Workspace />} />
    </Routes>
    </ThemeProvider>
  );
}

export default App;
