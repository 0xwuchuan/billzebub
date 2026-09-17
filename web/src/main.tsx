import { Agentation } from "agentation";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/screens.css";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Billzebub root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
    {import.meta.env.DEV ? (
      <Agentation endpoint="http://localhost:4747" />
    ) : null}
  </StrictMode>,
);
