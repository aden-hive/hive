import { Routes, Route } from "react-router-dom";
import Home from "./pages/home";
import Dashboard from "./pages/dashboard";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/dashboard" element={<Dashboard />} />
    </Routes>
  );
}

export default App;
