import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Outbox, OutboxStatus } from "./outbox";
import { OutboxContext, SyncBanner } from "./Sync";

/** An outbox whose status the test sets directly. */
function fakeOutbox(initial: OutboxStatus): Outbox & { set: (status: OutboxStatus) => void } {
  let status = initial;
  const listeners = new Set<() => void>();
  return {
    send: vi.fn(),
    flush: vi.fn(),
    idle: vi.fn(),
    queued: vi.fn(),
    start: vi.fn(),
    dismissRejected: vi.fn(() => Promise.resolve()),
    status: () => status,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    set(next): void {
      status = next;
      for (const listener of listeners) {
        listener();
      }
    },
  };
}

const clear: OutboxStatus = { pending: 0, rejected: [], offline: false };

function renderWith(outbox: Outbox): void {
  render(
    <OutboxContext value={outbox}>
      <SyncBanner />
    </OutboxContext>,
  );
}

describe("SyncBanner", () => {
  it("shows nothing without an outbox or with nothing to say", () => {
    const { container } = render(<SyncBanner />);
    expect(container).toBeEmptyDOMElement();

    renderWith(fakeOutbox(clear));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says what is still being saved, and when the phone is offline", () => {
    const outbox = fakeOutbox({ ...clear, pending: 1 });
    renderWith(outbox);

    expect(screen.getByRole("status")).toHaveTextContent("Saving 1 change…");

    act(() => {
      outbox.set({ ...clear, pending: 3, offline: true });
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Offline · 3 changes saved on this phone, sending when back online",
    );

    act(() => {
      outbox.set(clear);
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("lists refused changes until dismissed", () => {
    const outbox = fakeOutbox({
      ...clear,
      rejected: [
        {
          id: 4,
          method: "PUT",
          path: "/api/sets/a",
          body: {},
          label: "Set 2 of Bench",
          reason: "no workout",
        },
      ],
    });
    renderWith(outbox);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The server refused 1 change");
    expect(screen.getByRole("listitem")).toHaveTextContent("Set 2 of Bench: no workout");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(outbox.dismissRejected).toHaveBeenCalledOnce();
  });
});
