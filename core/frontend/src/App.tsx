import { Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import Home from "./pages/home";
import ColonyChat from "./pages/colony-chat";
import QueenDM from "./pages/queen-dm";
import OrgChart from "./pages/org-chart";
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
        <Route path="/credentials" element={<CredentialsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export default App;
