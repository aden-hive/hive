import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { ModelProvider } from "./context/ModelContext";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <ModelProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ModelProvider>
  </ThemeProvider>,
);
