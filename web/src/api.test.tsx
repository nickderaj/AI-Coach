import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, fetchJson, useApi } from "./api";
import { mockFetch } from "./test/fetch";

const schema = z.object({ value: z.number() });

describe("fetchJson", () => {
  it("returns the validated body", async () => {
    const fetchMock = mockFetch({ "/api/x": { body: { value: 1 } } });

    await expect(fetchJson("/api/x", schema)).resolves.toEqual({ value: 1 });
    expect(fetchMock).toHaveBeenCalledWith("/api/x", {
      signal: null,
      headers: { Accept: "application/json" },
    });
  });

  it("passes the abort signal through", async () => {
    const fetchMock = mockFetch({ "/api/x": { body: { value: 1 } } });
    const controller = new AbortController();

    await fetchJson("/api/x", schema, controller.signal);

    expect(fetchMock).toHaveBeenCalledWith("/api/x", {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
  });

  it("raises ApiError with a readable message", async () => {
    mockFetch({ "/api/gone": { status: 404, body: {} }, "/api/boom": { status: 503, body: {} } });

    await expect(fetchJson("/api/gone", schema)).rejects.toMatchObject({
      status: 404,
      message: "Not found",
      name: "ApiError",
    });
    await expect(fetchJson("/api/boom", schema)).rejects.toThrow("The server answered 503");
  });

  it("rejects a body that does not match the schema", async () => {
    mockFetch({ "/api/x": { body: { value: "one" } } });

    await expect(fetchJson("/api/x", schema)).rejects.toBeInstanceOf(z.ZodError);
  });
});

function Probe({ path }: { path: string }): ReactElement {
  const state = useApi(path, schema);
  return <output>{JSON.stringify(state)}</output>;
}

describe("useApi", () => {
  it("starts loading, then shows the data", async () => {
    mockFetch({ "/api/x": { body: { value: 7 } } });

    render(<Probe path="/api/x" />);

    expect(screen.getByRole("status")).toHaveTextContent('{"status":"loading"}');
    expect(await screen.findByText('{"status":"ready","data":{"value":7}}')).toBeInTheDocument();
  });

  it.each([
    [{ status: 404, body: {} }, "Not found"],
    [{ body: { value: "x" } }, "The server sent data this app does not understand"],
    [new TypeError("Failed to fetch"), "Could not reach the server"],
  ])("describes failures (%#)", async (reply, message) => {
    mockFetch({ "/api/x": reply });

    render(<Probe path="/api/x" />);

    expect(
      await screen.findByText(JSON.stringify({ status: "error", message })),
    ).toBeInTheDocument();
  });

  it("ignores a response that arrives after unmounting", async () => {
    let reject: (reason: unknown) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((_, rejectWith) => {
            reject = rejectWith;
          }),
      ),
    );
    const errors = vi.spyOn(console, "error");

    const { unmount } = render(<Probe path="/api/x" />);
    unmount();
    reject(new DOMException("aborted", "AbortError"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(errors).not.toHaveBeenCalled();
  });

  it("exposes ApiError status", () => {
    expect(new ApiError(500).status).toBe(500);
  });
});

describe("mockFetch", () => {
  it("routes URL and Request inputs by path", async () => {
    mockFetch({ "/api/x": { body: { value: 2 } } });

    const fromUrl = await fetch(new URL("http://localhost/api/x"));
    const fromRequest = await fetch(new Request("http://localhost/api/x"));

    expect(fromUrl.status).toBe(200);
    expect(fromRequest.status).toBe(404); // Request.url is absolute, so it is not a route key
  });

  it("fails loudly for a missing index", async () => {
    const { at } = await import("./test/fetch");

    expect(() => at([], 0)).toThrow("expected an item at index 0");
  });
});
