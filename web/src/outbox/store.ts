/**
 * Writes waiting for the server, kept in IndexedDB so they survive the app being
 * closed or the phone losing signal.
 *
 * Every write is an idempotent `PUT` or `DELETE` of one resource, so replaying
 * one twice is harmless. The queue holds at most one write per path:
 * - a `PUT` replaces the queued write for its path in place, keeping its turn,
 *   so a workout is still created before the sets that were logged into it;
 * - a `DELETE` drops whatever is queued for its path and joins the back, so it
 *   is sent after any queued write that depends on the resource existing.
 */

export interface Write {
  method: "PUT" | "DELETE";
  path: string;
  /** JSON body for a `PUT`; null for a `DELETE`. */
  body: unknown;
  /** What the change is, in words, for when the server refuses it. */
  label: string;
}

export interface QueuedWrite extends Write {
  id: number;
  /** Bumped when a newer `PUT` replaces this one while it may be in flight. */
  revision: number;
}

export interface RejectedWrite extends Write {
  id: number;
  reason: string;
}

export interface OutboxStore {
  add: (write: Write) => Promise<void>;
  /** The oldest queued write, if any. */
  next: () => Promise<QueuedWrite | undefined>;
  /**
   * Remove a write that the server accepted (`reason` null) or refused. Does
   * nothing if it was replaced after it was read, so the newer version is sent.
   */
  finish: (write: QueuedWrite, reason: string | null) => Promise<void>;
  pending: () => Promise<number>;
  rejected: () => Promise<RejectedWrite[]>;
  dismissRejected: () => Promise<void>;
}

const DATABASE = "trainer";
const VERSION = 1;
const OUTBOX = "outbox";
const REJECTED = "rejected";

function request<T>(pending: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    pending.onsuccess = (): void => {
      resolve(pending.result);
    };
    pending.onerror = (): void => {
      reject(pending.error ?? new Error("IndexedDB request failed"));
    };
  });
}

function committed(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = (): void => {
      resolve();
    };
    transaction.onabort = (): void => {
      reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
    };
  });
}

function openDatabase(factory: IDBFactory): Promise<IDBDatabase> {
  const opening = factory.open(DATABASE, VERSION);
  opening.onupgradeneeded = (): void => {
    const database = opening.result;
    database
      .createObjectStore(OUTBOX, { keyPath: "id", autoIncrement: true })
      .createIndex("path", "path");
    database.createObjectStore(REJECTED, { keyPath: "id", autoIncrement: true });
  };
  return request(opening);
}

/** The outbox in IndexedDB; the database is opened on first use. */
export function outboxStore(factory: IDBFactory): OutboxStore {
  let opened: Promise<IDBDatabase> | undefined;
  const database = (): Promise<IDBDatabase> => (opened ??= openDatabase(factory));

  async function transaction(names: string[], mode: IDBTransactionMode): Promise<IDBTransaction> {
    return (await database()).transaction(names, mode);
  }

  return {
    async add(write): Promise<void> {
      const tx = await transaction([OUTBOX], "readwrite");
      const outbox = tx.objectStore(OUTBOX);
      const queued = (await request(outbox.index("path").get(write.path))) as
        QueuedWrite | undefined;
      if (write.method === "PUT" && queued !== undefined) {
        outbox.put({ ...write, id: queued.id, revision: queued.revision + 1 });
      } else {
        if (queued !== undefined) {
          outbox.delete(queued.id);
        }
        outbox.add({ ...write, revision: 0 });
      }
      await committed(tx);
    },

    async next(): Promise<QueuedWrite | undefined> {
      const tx = await transaction([OUTBOX], "readonly");
      const [first] = (await request(tx.objectStore(OUTBOX).getAll(null, 1))) as QueuedWrite[];
      return first;
    },

    async finish(write, reason): Promise<void> {
      const tx = await transaction([OUTBOX, REJECTED], "readwrite");
      const outbox = tx.objectStore(OUTBOX);
      const current = (await request(outbox.get(write.id))) as QueuedWrite | undefined;
      if (current?.revision === write.revision) {
        outbox.delete(write.id);
        if (reason !== null) {
          const { method, path, body, label } = current;
          tx.objectStore(REJECTED).add({ method, path, body, label, reason });
        }
      }
      await committed(tx);
    },

    async pending(): Promise<number> {
      const tx = await transaction([OUTBOX], "readonly");
      return request(tx.objectStore(OUTBOX).count());
    },

    async rejected(): Promise<RejectedWrite[]> {
      const tx = await transaction([REJECTED], "readonly");
      return (await request(tx.objectStore(REJECTED).getAll())) as RejectedWrite[];
    },

    async dismissRejected(): Promise<void> {
      const tx = await transaction([REJECTED], "readwrite");
      tx.objectStore(REJECTED).clear();
      await committed(tx);
    },
  };
}
