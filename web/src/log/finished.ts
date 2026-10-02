/**
 * Program days finished on this phone, so a saved Today plan for a day already
 * done is never started again while the server cannot be asked (no signal).
 */
const KEY = "trainer.finished-days";
/** Plenty for a block of seven weeks; older ones can never come back. */
const KEEP = 60;

function read(storage: Storage): string[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function key(day_id: number, week: number): string {
  return `${String(day_id)}:${String(week)}`;
}

export function markFinished(storage: Storage, day_id: number, week: number): void {
  storage.setItem(KEY, JSON.stringify([...read(storage), key(day_id, week)].slice(-KEEP)));
}

export function finishedHere(storage: Storage, day_id: number, week: number): boolean {
  return read(storage).includes(key(day_id, week));
}
