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

type RestMediaSession = Pick<MediaSession, "metadata" | "playbackState">;
type RestAudioElement = Pick<HTMLAudioElement, "currentTime" | "pause" | "play" | "preload">;

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
  const stop = (): void => {
    audio.pause();
    audio.currentTime = 0;
    if (session !== null) {
      session.playbackState = "none";
    }
  };
  return {
    start: (seconds): void => {
      audio.currentTime = position(TRACK_SECONDS - seconds);
      if (session !== null) {
        session.playbackState = "playing";
      }
      void Promise.resolve(audio.play()).catch(() => undefined);
    },
    shift: (seconds): void => {
      audio.currentTime = position(audio.currentTime - seconds);
    },
    stop,
  };
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

/** Start the background-safe countdown from a set-completion tap. */
export function startRestAudio(milliseconds: number): void {
  browserController().start(milliseconds / 1000);
}

/** Apply the timer's adjustment to the audio timeline too. */
export function shiftRestAudio(milliseconds: number): void {
  browserController().shift(milliseconds / 1000);
}

/** Remove the rest timer from the system media surface. */
export function stopRestAudio(): void {
  if (controller !== null) {
    controller.stop();
  }
}
