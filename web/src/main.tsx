import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { DraftContext } from "./log/context";
import { draftStore } from "./log/store";
import { createOutbox, webLock } from "./outbox/outbox";
import { OutboxContext } from "./outbox/Sync";
import { outboxStore } from "./outbox/store";
import { routeToOpen } from "./sw/message";
import "./index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html is missing #root");
}

const outbox = createOutbox(
  outboxStore(indexedDB),
  // Missing before iOS 15.4, whatever the DOM types say; webLock allows for that.
  webLock(navigator.locks),
);
outbox.start();

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  // The worker speeds up and backs up reads, and shows notifications; the app
  // works without it.
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  // A tapped notification asks an open window to show its screen.
  navigator.serviceWorker.addEventListener("message", (event) => {
    const route = routeToOpen(event.data);
    if (route !== null) {
      window.location.hash = route;
    }
  });
}

createRoot(root).render(
  <StrictMode>
    <OutboxContext value={outbox}>
      <DraftContext value={draftStore(localStorage, window)}>
        <App />
      </DraftContext>
    </OutboxContext>
  </StrictMode>,
);
