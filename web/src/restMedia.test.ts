import { beforeEach, describe, expect, it, vi } from "vitest";

interface TestAudio {
  addEventListener: ReturnType<typeof vi.fn>;
  currentTime: number;
  pause: ReturnType<typeof vi.fn>;
  play: ReturnType<typeof vi.fn<() => Promise<void>>>;
  preload: string;
}

function fakeAudio(start = 0): TestAudio {
  return {
    addEventListener: vi.fn(),
    currentTime: start,
    pause: vi.fn(),
    play: vi.fn(() => Promise.resolve()),
    preload: "",
  };
}

function installAudio(audio: TestAudio): ReturnType<typeof vi.fn> {
  const AudioConstructor = vi.fn(function Audio(): TestAudio {
    return audio;
  });
  vi.stubGlobal("Audio", AudioConstructor);
  return AudioConstructor;
}

function listener(audio: TestAudio, type: string): EventListener {
  const call = audio.addEventListener.mock.calls.find((candidate) => candidate[0] === type);
  const found = call?.[1] as EventListener | undefined;
  if (found === undefined) {
    throw new TypeError(`${type} listener was not installed`);
  }
  return found;
}

function actionHandler(
  setActionHandler: ReturnType<typeof vi.fn>,
  action: MediaSessionAction,
): () => void {
  const call = setActionHandler.mock.calls.find((candidate) => candidate[0] === action);
  const found = call?.[1] as (() => void) | undefined;
  if (found === undefined) {
    throw new TypeError(`${action} handler was not installed`);
  }
  return found;
}

describe("rest media", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("publishes metadata and keeps one system media session aligned with the timer", async () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(1000);
    const audio = fakeAudio();
    const AudioConstructor = installAudio(audio);
    const metadata = vi.fn();
    const MediaMetadataConstructor = vi.fn(function MediaMetadata(init: MediaMetadataInit): object {
      metadata(init);
      return {};
    });
    const setActionHandler = vi.fn();
    const session = { metadata: null, playbackState: "none", setActionHandler };
    vi.stubGlobal("MediaMetadata", MediaMetadataConstructor);
    vi.stubGlobal("navigator", { mediaSession: session });
    vi.resetModules();
    const { setBackgroundRestEnabled, shiftRestMedia, startRestMedia, stopRestMedia } =
      await import("./restMedia");

    setBackgroundRestEnabled(localStorage, true);
    startRestMedia(90_000);
    expect(audio.currentTime).toBe(510);
    expect(session.playbackState).toBe("playing");
    now.mockReturnValue(31_000);
    actionHandler(setActionHandler, "play")();
    expect(audio.currentTime).toBe(540);
    shiftRestMedia(15_000);
    expect(audio.currentTime).toBe(525);
    startRestMedia(60_000);
    stopRestMedia();

    expect(AudioConstructor).toHaveBeenCalledOnce();
    expect(AudioConstructor).toHaveBeenCalledWith("/rest-countdown.m4a");
    expect(audio.preload).toBe("auto");
    expect(metadata).toHaveBeenCalledWith({
      title: "Rest timer",
      artist: "Coach",
      artwork: [{ src: "/icon-512.png", sizes: "512x512", type: "image/png" }],
    });
    expect(audio.play).toHaveBeenCalledTimes(3);
    expect(audio.pause).toHaveBeenCalledOnce();
    expect(audio.currentTime).toBe(0);
    expect(session.playbackState).toBe("none");
    expect(setActionHandler).toHaveBeenCalledTimes(6);
    expect(setActionHandler.mock.calls.every((call) => typeof call[1] === "function")).toBe(true);
    expect(actionHandler(setActionHandler, "pause")).not.toBe(
      actionHandler(setActionHandler, "play"),
    );
  });

  it("clamps seeks and ignores a browser refusal to play", async () => {
    const audio = fakeAudio();
    audio.play.mockRejectedValueOnce(new DOMException("blocked", "NotAllowedError"));
    installAudio(audio);
    vi.stubGlobal("navigator", {});
    vi.resetModules();
    const { setBackgroundRestEnabled, shiftRestMedia, startRestMedia } =
      await import("./restMedia");

    setBackgroundRestEnabled(localStorage, true);
    startRestMedia(590_000);
    expect(audio.currentTime).toBe(10);
    shiftRestMedia(700_000);
    expect(audio.currentTime).toBe(0);
    shiftRestMedia(-700_000);
    expect(audio.currentTime).toBe(0);
    await Promise.resolve();
    expect(audio.pause).toHaveBeenCalledTimes(2);
  });

  it("works when Media Session exists but MediaMetadata does not", async () => {
    const audio = fakeAudio();
    installAudio(audio);
    const session = { metadata: null, playbackState: "none", setActionHandler: vi.fn() };
    vi.stubGlobal("MediaMetadata", undefined);
    vi.stubGlobal("navigator", { mediaSession: session });
    vi.resetModules();
    const { setBackgroundRestEnabled, startRestMedia } = await import("./restMedia");

    setBackgroundRestEnabled(localStorage, true);
    startRestMedia(60_000);

    expect(audio.play).toHaveBeenCalledOnce();
    expect(session.metadata).toBeNull();
  });

  it("does not create media merely to stop an inactive timer", async () => {
    const AudioConstructor = vi.fn();
    vi.stubGlobal("Audio", AudioConstructor);
    vi.resetModules();
    const { setBackgroundRestEnabled, shiftRestMedia, startRestMedia, stopRestMedia } =
      await import("./restMedia");

    startRestMedia(60_000);
    startRestMedia(0);
    shiftRestMedia(15_000);
    setBackgroundRestEnabled(localStorage, false);
    stopRestMedia();

    expect(AudioConstructor).not.toHaveBeenCalled();
  });

  it("clears the media session when playback ends and tolerates unsupported controls", async () => {
    const audio = fakeAudio(540);
    installAudio(audio);
    const setActionHandler = vi.fn((action: MediaSessionAction) => {
      if (action === "seekto") {
        throw new DOMException("unsupported", "NotSupportedError");
      }
    });
    const session = { metadata: null, playbackState: "none", setActionHandler };
    vi.stubGlobal("navigator", { mediaSession: session });
    vi.resetModules();
    const { setBackgroundRestEnabled, startRestMedia } = await import("./restMedia");
    setBackgroundRestEnabled(localStorage, true);
    startRestMedia(60_000);

    listener(audio, "ended")(new Event("ended"));

    expect(audio.pause).toHaveBeenCalledOnce();
    expect(audio.currentTime).toBe(0);
    expect(session.playbackState).toBe("none");
    expect(setActionHandler).toHaveBeenCalledTimes(6);
  });
});
