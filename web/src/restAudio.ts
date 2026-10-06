/**
 * The rest clock's spoken 5, 4, 3, 2, 1.
 *
 * The voice is a five-second clip played through Web Audio with the page's
 * audio session set to "ambient", so iOS mixes it over music from another app
 * instead of pausing that music, and it never takes over the system's Now
 * Playing controls. iOS plays ambient audio only while Coach is on screen and
 * the ring switch is on; the on-screen clock is unaffected either way.
 */

/** The longest rest the timer allows. */
export const MAX_REST_MS = 600_000;

const CLIP_URL = "/rest-voice.m4a";
const CLIP_SECONDS = 5;
const VOICE_KEY = "coach.rest-voice";

type RestContext = Pick<
  AudioContext,
  "createBufferSource" | "currentTime" | "decodeAudioData" | "destination" | "resume"
>;
type RestStorage = Pick<Storage, "getItem" | "setItem">;

/** Safari's Audio Session API; absent from TypeScript's DOM types. */
interface AudioSessionNavigator {
  audioSession?: { type: string };
}

interface RestVoice {
  start: (seconds: number) => void;
  shift: (seconds: number) => void;
  stop: () => void;
  /** Re-place the clip after the page was hidden, when the audio clock may have paused. */
  resync: () => void;
}

/**
 * Schedule the clip against the audio clock so it lands on the timer's end
 * without relying on JavaScript timers.
 *
 * @internal Exported for tests; the app uses the functions below.
 */
export function restVoiceController(
  context: RestContext,
  load: () => Promise<ArrayBuffer>,
  now: () => number = Date.now,
): RestVoice {
  let endsAt: number | null = null;
  let clip: Promise<AudioBuffer> | null = null;
  let source: AudioBufferSourceNode | null = null;
  let generation = 0;

  const cancel = (): void => {
    generation += 1;
    source?.stop();
    source = null;
  };
  const decoded = async (): Promise<AudioBuffer | null> => {
    clip ??= load().then((bytes) => context.decodeAudioData(bytes));
    try {
      return await clip;
    } catch {
      clip = null;
      return null;
    }
  };
  const schedule = async (): Promise<void> => {
    cancel();
    const mine = generation;
    const buffer = await decoded();
    if (buffer === null || endsAt === null || mine !== generation) {
      return;
    }
    const lead = (endsAt - now()) / 1000 - CLIP_SECONDS;
    if (lead <= -CLIP_SECONDS) {
      return;
    }
    const node = context.createBufferSource();
    node.buffer = buffer;
    node.connect(context.destination);
    // Join a countdown already under way part-way through, as after +/- or a return.
    node.start(context.currentTime + Math.max(0, lead), Math.max(0, -lead));
    source = node;
  };
  const place = (): void => {
    void Promise.resolve(context.resume())
      .catch(() => undefined)
      .then(schedule);
  };

  return {
    start: (seconds): void => {
      endsAt = now() + seconds * 1000;
      place();
    },
    shift: (seconds): void => {
      if (endsAt !== null) {
        endsAt = Math.min(endsAt + seconds * 1000, now() + MAX_REST_MS);
        void schedule();
      }
    },
    stop: (): void => {
      endsAt = null;
      cancel();
    },
    resync: (): void => {
      if (endsAt !== null) {
        place();
      }
    },
  };
}

let controller: RestVoice | null = null;

/** The app's one controller, or null where the browser has no Web Audio. */
function browserController(): RestVoice | null {
  if (controller !== null || typeof AudioContext === "undefined") {
    return controller;
  }
  const session = (navigator as AudioSessionNavigator).audioSession;
  if (session !== undefined) {
    session.type = "ambient";
  }
  const voice = restVoiceController(new AudioContext(), async () => {
    const response = await fetch(CLIP_URL);
    if (!response.ok) {
      throw new Error(`${CLIP_URL} answered ${String(response.status)}`);
    }
    return response.arrayBuffer();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      voice.resync();
    }
  });
  controller = voice;
  return voice;
}

export function restVoiceEnabled(storage: RestStorage): boolean {
  return storage.getItem(VOICE_KEY) !== "off";
}

export function setRestVoiceEnabled(storage: RestStorage, enabled: boolean): void {
  storage.setItem(VOICE_KEY, enabled ? "on" : "off");
  if (!enabled) {
    stopRestAudio();
  }
}

/** Start the countdown from a set-completion tap, which lets the audio start. */
export function startRestAudio(milliseconds: number): void {
  if (milliseconds > 0 && restVoiceEnabled(localStorage)) {
    browserController()?.start(milliseconds / 1000);
  }
}

/** Apply the timer's adjustment to the countdown too. */
export function shiftRestAudio(milliseconds: number): void {
  controller?.shift(milliseconds / 1000);
}

/** Cancel the countdown. */
export function stopRestAudio(): void {
  controller?.stop();
}
