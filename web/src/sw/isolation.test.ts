import { describe, expect, it } from "vitest";

/**
 * The service worker is built as a classic script, which cannot `import`. If
 * the app and the worker shared a value, the bundler would move it into a chunk
 * that `sw.js` imports, and the worker would fail to start (and with it offline
 * reads and notifications). So app code imports nothing from the worker's
 * modules except `sw/message.ts`, and the worker imports only types from that one.
 */
const SOURCES: Record<string, string> = import.meta.glob(
  ["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/test/**"],
  { query: "?raw", import: "default", eager: true },
);
const IMPORT = /^import\s+(type\s+)?[^"']*["']([^"']+)["'];?$/gmu;

/** Paths relative to src/, as "sw/worker.ts". */
const FILES = Object.keys(SOURCES).map((path) => path.replace(/^\/src\//u, ""));

function imports(file: string): { typeOnly: boolean; from: string }[] {
  return [...(SOURCES[`/src/${file}`] ?? "").matchAll(IMPORT)].map((match) => ({
    typeOnly: match[1] !== undefined,
    from: match[2] ?? "",
  }));
}

describe("the service worker stays a single script", () => {
  it("finds the sources", () => {
    expect(FILES).toContain("main.tsx");
    expect(FILES).toContain("sw/worker.ts");
    expect(FILES).not.toContain("sw/notify.test.ts");
  });

  it("app code imports only sw/message.ts of the worker's modules", () => {
    const reached = FILES.filter((file) => !file.startsWith("sw/")).flatMap((file) =>
      imports(file)
        .filter(({ from }) => /(^|\/)sw\//u.test(from))
        .map(({ from }) => ({ file, module: from.replace(/^.*\bsw\//u, "sw/") })),
    );

    expect(reached.map(({ file }) => file)).toContain("main.tsx");
    expect(reached.filter(({ module }) => module !== "sw/message")).toEqual([]);
  });

  it("the worker imports only types from sw/message.ts", () => {
    const values = FILES.filter((file) => file.startsWith("sw/") && file !== "sw/message.ts")
      .flatMap((file) => imports(file).map((found) => ({ file, ...found })))
      .filter(({ from, typeOnly }) => from === "./message" && !typeOnly);

    expect(values).toEqual([]);
    expect(imports("sw/notify.ts")).toContainEqual({ typeOnly: true, from: "./message" });
  });
});
