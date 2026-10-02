import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { inboxSchema, readAllNotices, seeNotice, useApi } from "../api";
import type { InboxData, Notice } from "../api";
import { Load } from "../components";
import { formatDay, formatTime } from "../format";
import { href } from "../router";
import { INBOX_CHANGED } from "../sw/message";

const INBOX = "/api/inbox";

function NoticeItem({ notice, onRead }: { notice: Notice; onRead: () => void }): ReactElement {
  return (
    <li>
      <a
        className={notice.read ? "card inbox-item" : "card inbox-item unread"}
        href={notice.route}
        onClick={() => {
          // Read again once marked: a notice may open this very screen.
          void seeNotice(notice.id).then(onRead);
        }}
      >
        <span className="inbox-title">
          {notice.read ? null : <span className="dot" aria-label="Unread" />}
          <strong>{notice.title}</strong>
        </span>
        {notice.body === "" ? null : <span>{notice.body}</span>}
        <span className="muted">
          {formatDay(notice.at)} · {formatTime(notice.at)}
        </span>
      </a>
    </li>
  );
}

function Notices({ inbox, onRead }: { inbox: InboxData; onRead: () => void }): ReactElement {
  const [failed, setFailed] = useState(false);
  if (inbox.notices.length === 0) {
    return (
      <p className="muted">
        Nothing yet. When the coach answers while you are away, or proposes a program, it lands
        here.
      </p>
    );
  }
  return (
    <>
      {inbox.unread === 0 ? null : (
        <p className="row-actions inbox-actions">
          <span className="muted">{String(inbox.unread)} unread</span>
          <button
            type="button"
            className="link"
            onClick={() => {
              void readAllNotices().then((done) => {
                setFailed(!done);
                if (done) {
                  onRead();
                }
              });
            }}
          >
            Mark all read
          </button>
        </p>
      )}
      {failed ? (
        <p className="error" role="alert">
          Could not reach the server. Try again.
        </p>
      ) : null}
      <ul className="list" aria-label="Notices">
        {inbox.notices.map((notice) => (
          <NoticeItem key={notice.id} notice={notice} onRead={onRead} />
        ))}
      </ul>
    </>
  );
}

function InboxList({ onChanged }: { onChanged: () => void }): ReactElement {
  const state = useApi(INBOX, inboxSchema);
  return <Load state={state}>{(inbox) => <Notices inbox={inbox} onRead={onChanged} />}</Load>;
}

/** Every notice the app sent, newest first: nothing is lost if a push is. */
export function Inbox(): ReactElement {
  // Reading the inbox again after marking it read: a new list, a new load.
  const [loads, setLoads] = useState(0);
  useEffect(() => {
    const reload = (): void => {
      if (document.visibilityState === "visible") {
        setLoads((count) => count + 1);
      }
    };
    // Back from the background, or opened by a tapped notification: a notice
    // may have been read meanwhile.
    document.addEventListener("visibilitychange", reload);
    window.addEventListener(INBOX_CHANGED, reload);
    return (): void => {
      document.removeEventListener("visibilitychange", reload);
      window.removeEventListener(INBOX_CHANGED, reload);
    };
  }, []);
  return (
    <>
      <a className="back" href={href({ name: "home" })}>
        ‹ Home
      </a>
      <header className="page-head">
        <h1>Inbox</h1>
      </header>
      <InboxList
        key={loads}
        onChanged={() => {
          setLoads((count) => count + 1);
        }}
      />
    </>
  );
}
