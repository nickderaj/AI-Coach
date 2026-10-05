import { describe, expect, it, vi } from "vitest";

interface TestAudio {
  currentTime: number;
  pause: ReturnType<typeof vi.fn>;
  play: ReturnType<typeof vi.fn<() => Promise<void>>>;
  preload: string;
}

function fakeAudio(start = 0): TestAudio {
  return {
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

describe("rest audio", () => {
  it("publishes metadata and keeps one system media session aligned with the timer", async () => {
    const audio = fakeAudio();
    const AudioConstructor = installAudio(audio);
    const metadata = vi.fn();
    const MediaMetadataConstructor = vi.fn(function MediaMetadata(init: MediaMetadataInit): object {
      metadata(init);
      return {};
    });
    const session = { metadata: null, playbackState: "none" };
    vi.stubGlobal("MediaMetadata", MediaMetadataConstructor);
    vi.stubGlobal("navigator", { mediaSession: session });
    vi.resetModules();
    const { shiftRestAudio, startRestAudio, stopRestAudio } = await import("./restAudio");

    startRestAudio(90_000);
    expect(audio.currentTime).toBe(510);
    expect(session.playbackState).toBe("playing");
    shiftRestAudio(15_000);
    expect(audio.currentTime).toBe(495);
    startRestAudio(60_000);
    stopRestAudio();

    expect(AudioConstructor).toHaveBeenCalledOnce();
    expect(AudioConstructor).toHaveBeenCalledWith("/rest-countdown.m4a");
    expect(audio.preload).toBe("auto");
    expect(metadata).toHaveBeenCalledWith({
      title: "Rest timer",
      artist: "Coach",
      artwork: [{ src: "/icon-512.png", sizes: "512x512", type: "image/png" }],
    });
    expect(audio.play).toHaveBeenCalledTimes(2);
    expect(audio.pause).toHaveBeenCalledOnce();
    expect(audio.currentTime).toBe(0);
    expect(session.playbackState).toBe("none");
  });

  it("clamps seeks and ignores a browser refusal to play", async () => {
    const audio = fakeAudio();
    audio.play.mockRejectedValueOnce(new DOMException("blocked", "NotAllowedError"));
    installAudio(audio);
    vi.stubGlobal("navigator", {});
    vi.resetModules();
    const { shiftRestAudio, startRestAudio } = await import("./restAudio");

    startRestAudio(601_000);
    expect(audio.currentTime).toBe(0);
    shiftRestAudio(-700_000);
    expect(audio.currentTime).toBe(600);
    shiftRestAudio(700_000);
    expect(audio.currentTime).toBe(0);
    await Promise.resolve();
  });

  it("works when Media Session exists but MediaMetadata does not", async () => {
    const audio = fakeAudio();
    installAudio(audio);
    const session = { metadata: null, playbackState: "none" };
    vi.stubGlobal("MediaMetadata", undefined);
    vi.stubGlobal("navigator", { mediaSession: session });
    vi.resetModules();
    const { startRestAudio } = await import("./restAudio");

    startRestAudio(60_000);

    expect(audio.play).toHaveBeenCalledOnce();
    expect(session.metadata).toBeNull();
  });

  it("does not create media merely to stop an inactive timer", async () => {
    const AudioConstructor = vi.fn();
    vi.stubGlobal("Audio", AudioConstructor);
    vi.resetModules();
    const { stopRestAudio } = await import("./restAudio");

    stopRestAudio();

    expect(AudioConstructor).not.toHaveBeenCalled();
  });
});
