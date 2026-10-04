import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { askCoach, coachHistory, useReplyClaim } from "../api";
import type { CoachMessage } from "../api";

/** The server refuses longer messages. */
const MAX_MESSAGE = 4000;

type History =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; messages: CoachMessage[] };

function useHistory(): History {
  const [history, setHistory] = useState<History>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    void coachHistory(controller.signal).then((result) => {
      if (controller.signal.aborted) {
        return;
      }
      setHistory(
        result.kind === "ok"
          ? { status: "ready", messages: result.value }
          : { status: "error", message: result.message },
      );
    });
    return (): void => {
      controller.abort();
    };
  }, []);
  return history;
}

/** Loading, a failure to load, or a hint while nothing has been said. */
function HistoryNote({
  history,
  empty,
}: {
  history: History;
  empty: boolean;
}): ReactElement | null {
  if (history.status === "loading") {
    return <p className="muted">Loading…</p>;
  }
  if (history.status === "error") {
    return (
      <p className="error" role="alert">
        {history.message}
      </p>
    );
  }
  return empty ? (
    <p className="muted">Nothing said yet. Try “How did my last workout go?”</p>
  ) : null;
}

function Conversation({
  messages,
  waiting,
}: {
  messages: CoachMessage[];
  waiting: boolean;
}): ReactElement {
  // To the bottom of the page, not of the list: the composer and the space
  // kept for the tab bar sit below the last message, and would cover it.
  useEffect(() => {
    const page = document.scrollingElement ?? document.documentElement;
    page.scrollTop = page.scrollHeight;
  }, [messages.length, waiting]);
  return (
    <ol className="chat" aria-label="Conversation">
      {messages.map((message) => (
        <li
          key={`${message.role}-${message.at}-${message.text}`}
          className={`bubble ${message.role}`}
        >
          <span className="sr-only">{message.role === "user" ? "You: " : "Coach: "}</span>
          {message.text}
        </li>
      ))}
      {waiting ? (
        <li className="bubble assistant thinking" role="status">
          Thinking…
        </li>
      ) : null}
    </ol>
  );
}

function Composer({
  draft,
  waiting,
  onChange,
  onSend,
}: {
  draft: string;
  waiting: boolean;
  onChange: (draft: string) => void;
  onSend: () => void;
}): ReactElement {
  return (
    <form
      className="composer"
      aria-label="Message the coach"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <label className="sr-only" htmlFor="coach-message">
        Message
      </label>
      <textarea
        id="coach-message"
        rows={2}
        maxLength={MAX_MESSAGE}
        placeholder="Ask your coach…"
        value={draft}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
      <button type="submit" className="primary" disabled={waiting || draft.trim() === ""}>
        Send
      </button>
    </form>
  );
}

/** A message the coach did not get, and why. */
interface Failure {
  reason: string;
  unsent: string;
}

/** Why the last message failed, and the message itself unless it is back in the box. */
function FailureNote({
  failure,
  draft,
}: {
  failure: Failure | null;
  draft: string;
}): ReactElement | null {
  if (failure === null) {
    return null;
  }
  return (
    <div role="alert">
      <p className="error">{failure.reason}</p>
      {draft === failure.unsent ? null : (
        <p className="muted unsent">Not sent: “{failure.unsent}”</p>
      )}
    </div>
  );
}

/** The Coach tab: one long conversation with the coach, which needs a connection. */
export function Coach(): ReactElement {
  const history = useHistory();
  const claim = useReplyClaim();
  // What was said on this visit, after the history the server sent.
  const [said, setSaid] = useState<CoachMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const messages = [...(history.status === "ready" ? history.messages : []), ...said];

  const send = async (): Promise<void> => {
    const text = draft.trim();
    if (text === "" || waiting) {
      return;
    }
    const question: CoachMessage = { role: "user", text, at: new Date().toISOString() };
    setSaid((current) => [...current, question]);
    setDraft("");
    setFailure(null);
    setWaiting(true);
    const result = await askCoach(text);
    setWaiting(false);
    if (result.kind === "ok") {
      const reply = result.value;
      claim(reply);
      setSaid((current) => [...current, reply]);
      return;
    }
    // Take the question back. It returns to the box unless a new message has
    // been started there meanwhile; then it is shown with the reason instead.
    setSaid((current) => current.filter((message) => message !== question));
    setDraft((current) => (current.trim() === "" ? text : current));
    setFailure({ reason: result.message, unsent: text });
  };

  return (
    <>
      <header className="page-head">
        <h1>Coach</h1>
        <p className="muted">Ask about your training. It remembers what you tell it.</p>
      </header>
      <HistoryNote history={history} empty={messages.length === 0 && !waiting} />
      <Conversation messages={messages} waiting={waiting} />
      <FailureNote failure={failure} draft={draft} />
      <Composer
        draft={draft}
        waiting={waiting}
        onChange={setDraft}
        onSend={() => {
          void send();
        }}
      />
    </>
  );
}
