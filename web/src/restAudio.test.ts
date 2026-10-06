import { beforeEach, describe, expect, it, vi } from "vitest";

import { restVoiceController } from "./restAudio";

interface FakeSource {
  buffer: AudioBuffer | null;
  connect: ReturnType<typeof vi.fn>;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

const CLIP = { duration: 5 } as AudioBuffer;

interface FakeContext {
  context: {
    currentTime: number;
    destination: AudioDestinationNode;
    resume: ReturnType<typeof vi.fn<() => Promise<void>>>;
    decodeAudioData: ReturnType<typeof vi.fn<() => Promise<AudioBuffer>>>;
    createBufferSource: ReturnType<typeof vi.fn<() => AudioBufferSourceNode>>;
  };
  sources: FakeSource[];
}

interface FakeBrowser extends FakeContext {
  AudioContextConstructor: ReturnType<typeof vi.fn>;
  fetchClip: ReturnType<typeof vi.fn<() => Promise<Response>>>;
}

function fakeContext(currentTime = 100): FakeContext {
  const sources: FakeSource[] = [];
  const context = {
    currentTime,
    destination: {} as AudioDestinationNode,
    resume: vi.fn(() => Promise.resolve()),
    decodeAudioData: vi.fn(() => Promise.resolve(CLIP)),
    createBufferSource: vi.fn(() => {
      const source: FakeSource = { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn() };
      sources.push(source);
      return source as unknown as AudioBufferSourceNode;
    }),
  };
  return { context, sources };
}

/** Let the resume, load and decode promises settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
  }
}

describe("rest voice controller", () => {
  it("schedules the clip to finish as the rest ends and follows adjustments", async () => {
    let clock = 1_000;
    const { context, sources } = fakeContext();
    const load = vi.fn(() => Promise.resolve(new ArrayBuffer(8)));
    const voice = restVoiceController(context, load, () => clock);

    voice.start(90);
    expect(context.resume).toHaveBeenCalledOnce();
    await settle();
    expect(sources).toHaveLength(1);
    expect(sources[0]?.buffer).toBe(CLIP);
    expect(sources[0]?.connect).toHaveBeenCalledWith(context.destination);
    expect(sources[0]?.start).toHaveBeenCalledWith(185, 0);

    clock += 20_000;
    voice.shift(15);
    await settle();
    expect(sources[0]?.stop).toHaveBeenCalledOnce();
    expect(sources[1]?.start).toHaveBeenCalledWith(180, 0);

    voice.shift(-82);
    await settle();
    expect(sources[2]?.start).toHaveBeenCalledWith(100, 2);

    voice.stop();
    expect(sources[2]?.stop).toHaveBeenCalledOnce();
    voice.shift(15);
    voice.resync();
    await settle();
    expect(sources).toHaveLength(3);
    expect(load).toHaveBeenCalledOnce();
  });

  it("caps adjustments at ten minutes and stays silent once the rest is over", async () => {
    const clock = 0;
    const { context, sources } = fakeContext(0);
    const voice = restVoiceController(
      context,
      () => Promise.resolve(new ArrayBuffer(8)),
      () => clock,
    );

    voice.start(590);
    voice.shift(60);
    await settle();
    expect(sources.at(-1)?.start).toHaveBeenCalledWith(595, 0);

    voice.shift(-700);
    await settle();
    expect(sources).toHaveLength(1);
    expect(sources[0]?.stop).toHaveBeenCalledOnce();
  });

  it("re-places the clip when the page comes back", async () => {
    let clock = 0;
    const { context, sources } = fakeContext(0);
    const voice = restVoiceController(
      context,
      () => Promise.resolve(new ArrayBuffer(8)),
      () => clock,
    );

    voice.start(60);
    await settle();
    clock = 40_000;
    context.resume.mockRejectedValueOnce(new DOMException("blocked", "NotAllowedError"));
    voice.resync();
    await settle();

    expect(context.resume).toHaveBeenCalledTimes(2);
    expect(sources[1]?.start).toHaveBeenCalledWith(15, 0);
  });

  it("drops a schedule overtaken while the clip was loading", async () => {
    const { context, sources } = fakeContext(0);
    const voice = restVoiceController(
      context,
      () => Promise.resolve(new ArrayBuffer(8)),
      () => 0,
    );

    voice.start(60);
    voice.stop();
    await settle();

    expect(sources).toHaveLength(0);
  });

  it("retries the clip after it fails to load", async () => {
    const { context, sources } = fakeContext(0);
    const load = vi
      .fn<() => Promise<ArrayBuffer>>()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValue(new ArrayBuffer(8));
    const voice = restVoiceController(context, load, () => 0);

    voice.start(60);
    await settle();
    expect(sources).toHaveLength(0);
    voice.start(60);
    await settle();

    expect(load).toHaveBeenCalledTimes(2);
    expect(sources).toHaveLength(1);
  });
});

describe("rest audio", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  function installBrowser(ok = true): FakeBrowser {
    const { context, sources } = fakeContext(0);
    const AudioContextConstructor = vi.fn(function AudioContext() {
      return context;
    });
    const fetchClip = vi.fn(() =>
      Promise.resolve(new Response(ok ? "clip" : "", { status: ok ? 200 : 404 })),
    );
    vi.stubGlobal("AudioContext", AudioContextConstructor);
    vi.stubGlobal("fetch", fetchClip);
    return { AudioContextConstructor, context, fetchClip, sources };
  }

  it("mixes the countdown with other audio and resyncs on return", async () => {
    const audioSession = { type: "auto" };
    vi.stubGlobal("navigator", { audioSession });
    const { AudioContextConstructor, fetchClip, sources } = installBrowser();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    const { shiftRestAudio, startRestAudio, stopRestAudio } = await import("./restAudio");

    startRestAudio(60_000);
    await settle();
    shiftRestAudio(15_000);
    startRestAudio(30_000);
    await settle();
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    stopRestAudio();

    expect(audioSession.type).toBe("ambient");
    expect(AudioContextConstructor).toHaveBeenCalledOnce();
    expect(fetchClip).toHaveBeenCalledExactlyOnceWith("/rest-voice.m4a");
    expect(sources.at(-1)?.stop).toHaveBeenCalledOnce();
  });

  it("ignores a hidden page and a clip that cannot be fetched", async () => {
    vi.stubGlobal("navigator", {});
    const { sources } = installBrowser(false);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const { startRestAudio } = await import("./restAudio");

    startRestAudio(60_000);
    await settle();
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();

    expect(sources).toHaveLength(0);
  });

  it("leaves the countdown to the background timer when that is on", async () => {
    const { AudioContextConstructor } = installBrowser();
    const media = {
      addEventListener: vi.fn(),
      currentTime: 0,
      pause: vi.fn(),
      play: vi.fn(() => Promise.resolve()),
      preload: "",
    };
    const AudioConstructor = vi.fn(function Audio() {
      return media;
    });
    vi.stubGlobal("Audio", AudioConstructor);
    vi.stubGlobal("navigator", {});
    const { setBackgroundRestEnabled } = await import("./restMedia");
    const { shiftRestAudio, startRestAudio, stopRestAudio } = await import("./restAudio");

    setBackgroundRestEnabled(localStorage, true);
    startRestAudio(60_000);
    shiftRestAudio(15_000);
    stopRestAudio();

    expect(AudioConstructor).toHaveBeenCalledExactlyOnceWith("/rest-countdown.m4a");
    expect(media.play).toHaveBeenCalledOnce();
    expect(media.pause).toHaveBeenCalledOnce();
    expect(AudioContextConstructor).not.toHaveBeenCalled();
  });

  it("stays silent without Web Audio", async () => {
    vi.stubGlobal("AudioContext", undefined);
    const { startRestAudio } = await import("./restAudio");

    expect(() => {
      startRestAudio(60_000);
    }).not.toThrow();
  });

  it("stays silent when turned off and creates no audio merely to stop", async () => {
    const { AudioContextConstructor } = installBrowser();
    const { restVoiceEnabled, setRestVoiceEnabled, shiftRestAudio, startRestAudio, stopRestAudio } =
      await import("./restAudio");

    expect(restVoiceEnabled(localStorage)).toBe(true);
    setRestVoiceEnabled(localStorage, false);
    startRestAudio(60_000);
    startRestAudio(0);
    shiftRestAudio(15_000);
    stopRestAudio();
    expect(AudioContextConstructor).not.toHaveBeenCalled();

    setRestVoiceEnabled(localStorage, true);
    expect(restVoiceEnabled(localStorage)).toBe(true);
  });
});
