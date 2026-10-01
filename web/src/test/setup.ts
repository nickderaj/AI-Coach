import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom does not implement scrolling. (Tests in the node environment have no DOM.)
if ("Element" in globalThis) {
  Element.prototype.scrollIntoView = (): void => undefined;
}

afterEach(() => {
  cleanup();
});
