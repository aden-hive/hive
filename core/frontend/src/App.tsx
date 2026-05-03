import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import PageLoader from "@/components/PageLoader";
import RouteErrorBoundary from "@/components/RouteErrorBoundary";

const Home = lazy(() => import("./pages/home"));
const ColonyChat = lazy(() => import("./pages/colony-chat"));
const QueenDM = lazy(() => import("./pages/queen-dm"));
const QueenRouting = lazy(() => import("./pages/queen-routing"));
const OrgChart = lazy(() => import("./pages/org-chart"));
const PromptLibrary = lazy(() => import("./pages/prompt-library"));
const SkillsLibrary = lazy(() => import("./pages/skills-library"));
const ToolLibrary = lazy(() => import("./pages/tool-library"));
const CredentialsPage = lazy(() => import("./pages/credentials"));
const NotFound = lazy(() => import("./pages/not-found"));

function App() {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/colony/:colonyId" element={<ColonyChat />} />
            <Route path="/queen-routing" element={<QueenRouting />} />
            <Route path="/queen/:queenId" element={<QueenDM />} />
            <Route path="/org-chart" element={<OrgChart />} />
            <Route path="/skills-library" element={<SkillsLibrary />} />
            <Route path="/prompt-library" element={<PromptLibrary />} />
            <Route path="/tool-library" element={<ToolLibrary />} />
            <Route path="/credentials" element={<CredentialsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </RouteErrorBoundary>
  );
}

export default App;
