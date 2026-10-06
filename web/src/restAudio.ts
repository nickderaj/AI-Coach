/**
 * The rest clock's system-media companion.
 *
 * iOS pauses background JavaScript timers, but continues an audio element that
 * was started by a tap. The ten-minute track is silent until its final five
 * seconds, where it contains the spoken countdown. Seeking to `duration - rest`
 * therefore keeps both the voice and the system's remaining-time display in
 * step with the on-screen clock.
 */

const TRACK_SECONDS = 600;
const TRACK_URL = "/rest-countdown.m4a";
const BACKGROUND_REST_KEY = "coach.background-rest";
export const MAX_REST_MS = TRACK_SECONDS * 1000;

type RestMediaSession = Pick<MediaSession, "metadata" | "playbackState" | "setActionHandler">;
type RestAudioElement = Pick<
  HTMLAudioElement,
  "addEventListener" | "currentTime" | "pause" | "play" | "preload"
>;
type RestStorage = Pick<Storage, "getItem" | "setItem">;

interface RestAudio {
  start: (seconds: number) => void;
  shift: (seconds: number) => void;
  stop: () => void;
}

function position(seconds: number): number {
  return Math.min(TRACK_SECONDS, Math.max(0, seconds));
}

/** Build the controller separately from browser globals so its timing is testable. */
function restAudioController(audio: RestAudioElement, session: RestMediaSession | null): RestAudio {
  let endsAt: number | null = null;
  const stop = (): void => {
    endsAt = null;
    audio.pause();
    audio.currentTime = 0;
    if (session !== null) {
      session.playbackState = "none";
    }
  };
  const sync = (): void => {
    if (endsAt === null) {
      return;
    }
    const seconds = (endsAt - Date.now()) / 1000;
    if (seconds <= 0) {
      stop();
      return;
    }
    audio.currentTime = position(TRACK_SECONDS - seconds);
  };
  const resume = (): void => {
    sync();
    if (endsAt !== null) {
      void Promise.resolve(audio.play()).catch(stop);
    }
  };
  audio.addEventListener("ended", stop);
  audio.addEventListener("play", sync);
  if (session !== null) {
    configureSystemControls(session, resume);
  }
  return {
    start: (seconds): void => {
      endsAt = Date.now() + seconds * 1000;
      if (session !== null) {
        session.playbackState = "playing";
      }
      resume();
    },
    shift: (seconds): void => {
      if (endsAt !== null) {
        const remaining = position((endsAt - Date.now()) / 1000 + seconds);
        endsAt = Date.now() + remaining * 1000;
        sync();
      }
    },
    stop,
  };
}

const SYSTEM_ACTIONS: MediaSessionAction[] = [
  "pause",
  "seekbackward",
  "seekforward",
  "seekto",
  "stop",
];

function configureSystemControls(session: RestMediaSession, resume: () => void): void {
  const ignore = (): void => undefined;
  for (const action of SYSTEM_ACTIONS) {
    try {
      session.setActionHandler(action, ignore);
    } catch {
      // Safari versions expose different subsets; disable every action they accept.
    }
  }
  try {
    session.setActionHandler("play", resume);
  } catch {
    // Some Safari versions do not expose the play action.
  }
}

let controller: RestAudio | null = null;

function browserController(): RestAudio {
  if (controller !== null) {
    return controller;
  }
  const audio = new Audio(TRACK_URL);
  audio.preload = "auto";
  const session = "mediaSession" in navigator ? navigator.mediaSession : null;
  if (session !== null && typeof MediaMetadata === "function") {
    session.metadata = new MediaMetadata({
      title: "Rest timer",
      artist: "Coach",
      artwork: [{ src: "/icon-512.png", sizes: "512x512", type: "image/png" }],
    });
  }
  controller = restAudioController(audio, session);
  return controller;
}

export function backgroundRestEnabled(storage: RestStorage): boolean {
  return storage.getItem(BACKGROUND_REST_KEY) === "on";
}

export function setBackgroundRestEnabled(storage: RestStorage, enabled: boolean): void {
  storage.setItem(BACKGROUND_REST_KEY, enabled ? "on" : "off");
  if (!enabled) {
    stopRestAudio();
  }
}

/** Start the background-safe countdown from a set-completion tap. */
export function startRestAudio(milliseconds: number): void {
  if (milliseconds > 0 && backgroundRestEnabled(localStorage)) {
    browserController().start(milliseconds / 1000);
  }
}

/** Apply the timer's adjustment to the audio timeline too. */
export function shiftRestAudio(milliseconds: number): void {
  controller?.shift(milliseconds / 1000);
}

/** Remove the rest timer from the system media surface. */
export function stopRestAudio(): void {
  if (controller !== null) {
    controller.stop();
  }
}
