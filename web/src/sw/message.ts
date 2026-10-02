/**
 * The message the service worker posts to an open window of the app when a
 * notification is tapped, and the app's reading of it.
 *
 * The app imports this module, so the worker may import only its types:
 * a value shared by both would be split into a chunk the worker imports, and a
 * classic service worker cannot import anything.
 */

/** Asks an open window to show a screen. */
export interface OpenMessage {
  type: "open";
  route: string;
}

/**
 * The window event the app fires when a tapped notification opens a screen:
 * its notice has just been marked read, so the inbox should be read again.
 */
export const INBOX_CHANGED = "trainer:inbox-changed";

/** Only routes of this app are opened (as in `notify.ts`). */
const ROUTE = /^#\/[a-z/]*$/;

/** The route in a worker's message to the app, if it is one to open. */
export function routeToOpen(data: unknown): string | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const { type, route } = data as Record<string, unknown>;
  return type === "open" && typeof route === "string" && ROUTE.test(route) ? route : null;
}
