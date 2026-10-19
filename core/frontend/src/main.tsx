import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { ModelProvider } from "./context/ModelContext";
import { RuntimeProvider } from "./context/RuntimeContext";
import { ConfigurationGate } from "./context/ConfigurationGate";
import { LiveSessionsProvider } from "./hooks/use-live-sessions";
import App from "./App";

// Typography: Geist (UI) + Geist Mono (code/labels), variable weights.
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";

import "./index.css";

// Local-mode provider tree. The desktop app's cloud gates (auth, workspace,
// subscription, analytics, update-required) are stripped in the OSS web build:
// the runtime is served same-origin and owns its own HIVE_HOME, so there is no
// sign-in step.
//   1. RuntimeProvider     — reports the runtime as ready (served alongside us).
//   2. ConfigurationGate   — waits for the runtime to listen (never for model
//                            setup: chats link to the model settings instead).
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
