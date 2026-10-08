import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { ModelProvider } from "./context/ModelContext";
import { RuntimeProvider } from "./context/RuntimeContext";
import { ConfigurationGate } from "./context/ConfigurationGate";
import { LiveSessionsProvider } from "./hooks/use-live-sessions";
import App from "./App";

// Typography: Inter Tight (UI) + JetBrains Mono (code/labels)
import "@fontsource/inter-tight/400.css";
import "@fontsource/inter-tight/500.css";
import "@fontsource/inter-tight/600.css";
import "@fontsource/inter-tight/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";

import "./index.css";

// Local-mode provider tree. The desktop app's cloud gates (auth, workspace,
// subscription, analytics, update-required) are stripped in the OSS web build:
// the runtime is served same-origin and owns its own HIVE_HOME, so there is no
// sign-in step.
//   1. RuntimeProvider     — reports the runtime as ready (served alongside us).
//   2. ConfigurationGate   — requires at least one BYOK LLM provider configured
//                            (per the runtime's /api/config credentials).
//   3. ModelProvider       — fetches the runtime's LLM catalogue.
//   4. App                 — the main product tree.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <HashRouter>
      <RuntimeProvider>
        <LiveSessionsProvider>
          <ConfigurationGate>
            <ModelProvider>
              <App />
            </ModelProvider>
          </ConfigurationGate>
        </LiveSessionsProvider>
      </RuntimeProvider>
    </HashRouter>
  </ThemeProvider>,
);
