import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

if (typeof HTMLMediaElement !== "undefined") {
  Object.defineProperties(HTMLMediaElement.prototype, {
    pause: { configurable: true, value: (): void => undefined },
    play: { configurable: true, value: (): Promise<void> => Promise.resolve() },
  });
}

afterEach(() => {
  cleanup();
});
