"use client";

export type StreamKind = "audio" | "video";

export type StreamConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

interface StreamingControllerCallbacks {
  onStatusChange?: (stream: StreamKind, state: StreamConnectionState) => void;
  onError?: (stream: StreamKind, message: string) => void;
}

interface StreamingControllerOptions extends StreamingControllerCallbacks {
  audioStream: MediaStream;
  videoStream: MediaStream;
  audioUrl: string;
  videoUrl: string;
  token?: string;
  chunkDurationMs?: number;
}

type ReconnectTimers = Partial<Record<StreamKind, number>>;

const DEFAULT_CHUNK_DURATION = 1000;

export class StreamingController {
  private readonly audioStream: MediaStream;

  private readonly videoStream: MediaStream;

  private readonly audioUrl: string;

  private readonly videoUrl: string;

  private readonly token?: string;

  private readonly onStatusChange?: StreamingControllerCallbacks["onStatusChange"];

  private readonly onError?: StreamingControllerCallbacks["onError"];

  private readonly chunkDuration: number;

  private audioRecorder?: MediaRecorder;

  private videoRecorder?: MediaRecorder;

  private audioSocket?: WebSocket;

  private videoSocket?: WebSocket;

  private sequence: Record<StreamKind, number> = { audio: 0, video: 0 };

  private reconnectTimers: ReconnectTimers = {};

  private recorderMimeTypes: Record<StreamKind, string> = {
    audio: "audio/webm",
    video: "video/webm"
  };

  private dataRequestTimers: Partial<Record<StreamKind, number>> = {};

  private running = false;

  constructor(options: StreamingControllerOptions) {
    this.audioStream = options.audioStream;
    this.videoStream = options.videoStream;
    this.audioUrl = options.audioUrl;
    this.videoUrl = options.videoUrl;
    this.token = options.token;
    this.onStatusChange = options.onStatusChange;
    this.onError = options.onError;
    this.chunkDuration = options.chunkDurationMs ?? DEFAULT_CHUNK_DURATION;
  }

  start() {
    if (this.running) {
      return;
    }
    this.running = true;

    this.openSocket("audio");
    this.openSocket("video");
    this.startRecorder("audio");
    this.startRecorder("video");
  }

  stop() {
    if (!this.running) {
      return;
    }
    this.running = false;

    this.stopRecorder("audio");
    this.stopRecorder("video");
    this.closeSocket("audio", 1000, "client closed audio stream");
    this.closeSocket("video", 1000, "client closed video stream");
    this.clearReconnectTimer("audio");
    this.clearReconnectTimer("video");
    this.clearDataRequestTimer("audio");
    this.clearDataRequestTimer("video");
    this.sequence = { audio: 0, video: 0 };
    this.updateStatus("audio", "idle");
    this.updateStatus("video", "idle");
  }

  private startRecorder(kind: StreamKind) {
    if (typeof MediaRecorder === "undefined") {
      this.handleError(kind, "MediaRecorder API is not supported in this browser.");
      return;
    }

    // Stop any existing recorder first to avoid "already recording" errors
    const existingRecorder = kind === "audio" ? this.audioRecorder : this.videoRecorder;
    if (existingRecorder && existingRecorder.state !== "inactive") {
      try {
        existingRecorder.stop();
      } catch (error) {
        console.warn(`[${kind}] Failed to stop existing recorder:`, error);
      }
    }

    const stream = kind === "audio" ? this.audioStream : this.videoStream;
    const options = this.selectRecorderOptions(kind);

    try {
      const recorder = new MediaRecorder(stream, options);
      this.recorderMimeTypes[kind] = recorder.mimeType || options?.mimeType || this.recorderMimeTypes[kind];

      recorder.ondataavailable = async (event: BlobEvent) => {
        if (!event.data || event.data.size === 0) {
          return;
        }

        try {
          const buffer = await event.data.arrayBuffer();
          this.sendChunk(kind, buffer);
        } catch (error) {
          this.handleError(kind, `Failed to process ${kind} chunk: ${(error as Error).message}`);
        }
      };

      recorder.onerror = (event: Event) => {
        const error = (event as { error?: DOMException }).error;
        const message = error ? `${error.name}: ${error.message}` : "Unknown recorder error";
        this.handleError(kind, `MediaRecorder error: ${message}`);
        this.updateStatus(kind, "error");
      };

      recorder.onstop = () => {
        if (this.running) {
          // Recorder should not stop while running; restart to maintain streaming.
          this.startRecorder(kind);
        }
        this.clearDataRequestTimer(kind);
      };

      try {
        recorder.start(this.chunkDuration);
      } catch (startError) {
        console.warn(`[${kind}] recorder.start(${this.chunkDuration}) failed, retrying without timeslice`, startError);
        try {
          recorder.start();
          if (this.chunkDuration > 0) {
            this.scheduleDataRequest(kind, recorder);
          }
        } catch (retryError) {
          this.handleError(kind, `Unable to start MediaRecorder: ${(retryError as Error).message}`);
          this.updateStatus(kind, "error");
          return;
        }
      }

      if (kind === "audio") {
        this.audioRecorder = recorder;
      } else {
        this.videoRecorder = recorder;
      }
    } catch (error) {
      this.handleError(kind, `Unable to start MediaRecorder: ${(error as Error).message}`);
    }
  }

  private stopRecorder(kind: StreamKind) {
    const recorder = kind === "audio" ? this.audioRecorder : this.videoRecorder;
    if (!recorder) {
      return;
    }

    if (recorder.state !== "inactive") {
      recorder.stop();
    }

    this.clearDataRequestTimer(kind);

    if (kind === "audio") {
      this.audioRecorder = undefined;
    } else {
      this.videoRecorder = undefined;
    }
  }

  private openSocket(kind: StreamKind) {
    const url = kind === "audio" ? this.audioUrl : this.videoUrl;
    if (!url) {
      this.handleError(kind, "WebSocket URL is not configured.");
      return;
    }

    this.updateStatus(kind, "connecting");

    try {
      const socketUrl = this.composeSocketUrl(url);
      const socket = new WebSocket(socketUrl);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        this.updateStatus(kind, "connected");
      };

      socket.onerror = () => {
        this.handleError(kind, `${kind} WebSocket encountered an error.`);
        this.updateStatus(kind, "error");
      };

      socket.onclose = (event) => {
        this.updateStatus(kind, "disconnected");
        if (this.running && event.code !== 1000) {
          this.scheduleReconnect(kind);
        }
      };

      socket.onmessage = (event) => {
        if (typeof event.data === "string") {
          // Forward server messages to console for easier debugging.
          console.debug(`[${kind}]`, event.data);
        }
      };

      if (kind === "audio") {
        this.audioSocket = socket;
      } else {
        this.videoSocket = socket;
      }
    } catch (error) {
      this.handleError(kind, `Failed to open WebSocket: ${(error as Error).message}`);
      this.scheduleReconnect(kind);
    }
  }

  private closeSocket(kind: StreamKind, code?: number, reason?: string) {
    const socket = kind === "audio" ? this.audioSocket : this.videoSocket;
    if (!socket) {
      return;
    }

    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close(code, reason);
    }

    if (kind === "audio") {
      this.audioSocket = undefined;
    } else {
      this.videoSocket = undefined;
    }
  }

  private sendChunk(kind: StreamKind, buffer: ArrayBuffer) {
    const socket = kind === "audio" ? this.audioSocket : this.videoSocket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }

    const mimeType = this.recorderMimeTypes[kind];
    const sequence = ++this.sequence[kind];

    const metadata = JSON.stringify({
      sequence,
      capturedAt: new Date().toISOString(),
      mimeType,
      chunkSize: buffer.byteLength,
      streamType: kind
    });

    socket.send(metadata);
    socket.send(buffer);
  }

  private selectRecorderOptions(kind: StreamKind): MediaRecorderOptions | undefined {
    if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported === "undefined") {
      return undefined;
    }

    const candidates =
      kind === "video"
        ? ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4;codecs=h264,aac", "video/mp4"]
        : ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4;codecs=aac", "audio/mp4"];

    for (const mimeType of candidates) {
      if (MediaRecorder.isTypeSupported(mimeType)) {
        return { mimeType };
      }
    }

    return undefined;
  }

  private composeSocketUrl(raw: string): string {
    try {
      const url = new URL(raw, typeof window !== "undefined" ? window.location.href : undefined);
      if (this.token) {
        url.searchParams.set("token", this.token);
      }
      return url.toString();
    } catch (error) {
      console.error("Invalid WebSocket URL", error);
      return raw;
    }
  }

  private scheduleReconnect(kind: StreamKind) {
    if (!this.running) {
      return;
    }

    this.clearReconnectTimer(kind);
    const timeout = window.setTimeout(() => this.openSocket(kind), 1000);
    this.reconnectTimers[kind] = timeout;
  }

  private clearReconnectTimer(kind: StreamKind) {
    const timer = this.reconnectTimers[kind];
    if (timer) {
      window.clearTimeout(timer);
      delete this.reconnectTimers[kind];
    }
  }

  private updateStatus(kind: StreamKind, state: StreamConnectionState) {
    this.onStatusChange?.(kind, state);
  }

  private handleError(kind: StreamKind, message: string) {
    console.error(`[${kind}] ${message}`);
    this.onError?.(kind, message);
  }

  private scheduleDataRequest(kind: StreamKind, recorder: MediaRecorder) {
    this.clearDataRequestTimer(kind);
    if (typeof window === "undefined") {
      return;
    }

    const interval = window.setInterval(() => {
      if (!this.running || recorder.state !== "recording") {
        return;
      }
      try {
        recorder.requestData();
      } catch (error) {
        console.warn(`[${kind}] Failed to request MediaRecorder data chunk`, error);
      }
    }, this.chunkDuration);

    this.dataRequestTimers[kind] = interval;
  }

  private clearDataRequestTimer(kind: StreamKind) {
    const timer = this.dataRequestTimers[kind];
    if (timer) {
      window.clearInterval(timer);
      delete this.dataRequestTimers[kind];
    }
  }
}

export function createMediaStreams(source: MediaStream | null): {
  audio: MediaStream | null;
  video: MediaStream | null;
} {
  if (!source) {
    return { audio: null, video: null };
  }

  const audioTracks = source.getAudioTracks();
  const videoTracks = source.getVideoTracks();

  return {
    audio: audioTracks.length ? new MediaStream([audioTracks[0]]) : null,
    video: videoTracks.length ? new MediaStream([videoTracks[0]]) : null
  };
}
