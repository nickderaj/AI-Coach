import { render } from "@testing-library/react";
import { vi } from "vitest";
import type { Mock } from "vitest";

import { App } from "../App";
import { DraftContext } from "../log/context";
import type { Draft } from "../log/draft";
import { draftStore } from "../log/store";
import type { DraftStore } from "../log/store";
import type { Outbox } from "../outbox/outbox";
import { OutboxContext } from "../outbox/Sync";
import type { Write } from "../outbox/store";

export type FakeOutbox = Outbox & { send: Mock<(write: Write) => Promise<void>> };

const CLEAR = { pending: 0, rejected: [], offline: false };

/** An outbox that records what would be sent. */
function fakeOutbox(): FakeOutbox {
  return {
    send: vi.fn(() => Promise.resolve()),
    flush: () => Promise.resolve(),
    idle: () => Promise.resolve(),
    dismissRejected: () => Promise.resolve(),
    subscribe: () => () => undefined,
    status: () => CLEAR,
    start: () => () => undefined,
  };
}

/** The writes sent so far, as "METHOD path" plus the body. */
export function writes(outbox: FakeOutbox): [string, unknown][] {
  return outbox.send.mock.calls.map(([write]) => [`${write.method} ${write.path}`, write.body]);
}

/** Render the whole app with logging available, optionally mid-workout. */
export function renderLogging(draft: Draft | null = null): {
  outbox: FakeOutbox;
  drafts: DraftStore;
} {
  const outbox = fakeOutbox();
  const drafts = draftStore(localStorage);
  drafts.set(draft);
  render(
    <OutboxContext value={outbox}>
      <DraftContext value={drafts}>
        <App />
      </DraftContext>
    </OutboxContext>,
  );
  return { outbox, drafts };
}

type Reply = { status?: number; body: unknown } | Error;

/** Replace fetch with canned replies keyed by "METHOD path". */
export function routeFetch(routes: Record<string, Reply>): Mock<typeof fetch> {
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path =
      typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const reply = routes[`${init?.method ?? "GET"} ${path}`];
    if (reply === undefined) {
      return Promise.resolve(new Response("{}", { status: 404 }));
    }
    if (reply instanceof Error) {
      return Promise.reject(reply);
    }
    return Promise.resolve(
      new Response(JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
