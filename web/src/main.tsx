import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createOutbox } from "./outbox/outbox";
import { OutboxContext } from "./outbox/Sync";
import { outboxStore } from "./outbox/store";
import "./index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html is missing #root");
}

const outbox = createOutbox(outboxStore(indexedDB));
outbox.start();

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  // The worker only speeds up and backs up reads; the app works without it.
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}

createRoot(root).render(
  <StrictMode>
    <OutboxContext value={outbox}>
      <App />
    </OutboxContext>
  </StrictMode>,
);
