"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AudioVisualizer } from "../components/AudioVisualizer";
import { StreamControls } from "../components/StreamControls";
import { VideoCapture, type PermissionState } from "../components/VideoCapture";
import {
  StreamingController,
  type StreamConnectionState,
  type StreamKind,
  createMediaStreams
} from "../lib/websocket";

type StreamErrorState = Record<StreamKind, string | null>;
type ConnectionStateMap = Record<StreamKind, StreamConnectionState>;

const videoWsUrl = process.env.NEXT_PUBLIC_VIDEO_WS_URL ?? "";
const audioWsUrl = process.env.NEXT_PUBLIC_AUDIO_WS_URL ?? "";
const streamToken = process.env.NEXT_PUBLIC_STREAM_TOKEN ?? "";
const chunkDurationEnv = process.env.NEXT_PUBLIC_CHUNK_DURATION_MS ?? "";
const chunkDurationMs = Number.parseInt(chunkDurationEnv, 10);

const initialConnectionState: ConnectionStateMap = {
  audio: "idle",
  video: "idle"
};

export default function HomePage() {
  const [permission, setPermission] = useState<PermissionState>("idle");
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const [audioStream, setAudioStream] = useState<MediaStream | null>(null);
  const [videoStream, setVideoStream] = useState<MediaStream | null>(null);
  const [controller, setController] = useState<StreamingController | null>(null);
  const [connectionStates, setConnectionStates] = useState<ConnectionStateMap>(
    () => ({ ...initialConnectionState })
  );
  const [streamErrors, setStreamErrors] = useState<StreamErrorState>({
    audio: null,
    video: null
  });
  const [generalError, setGeneralError] = useState<string | null>(null);

  const chunkDuration = Number.isNaN(chunkDurationMs) ? undefined : chunkDurationMs;

  useEffect(() => {
    const { audio, video } = createMediaStreams(mediaStream);
    setAudioStream(audio);
    setVideoStream(video);
  }, [mediaStream]);

  useEffect(() => {
    return () => {
      controller?.stop();
      mediaStream?.getTracks().forEach((track) => track.stop());
    };
  }, [controller, mediaStream]);

  const requestPermissions = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setPermission("denied");
      setPermissionError("MediaDevices API not available in this browser.");
      return;
    }

    setPermission("pending");
    setPermissionError(null);

    try {
      controller?.stop();
      setController(null);
      setConnectionStates({ audio: "idle", video: "idle" });
      mediaStream?.getTracks().forEach((track) => track.stop());

      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
        audio: true
      });

      setMediaStream(stream);
      setPermission("granted");
    } catch (error) {
      const message =
        (error as Error).message ||
        "Unable to access camera/microphone. Please check your browser settings.";
      setPermission("denied");
      setPermissionError(message);
    }
  }, [controller, mediaStream]);

  const handleStartStreaming = useCallback(() => {
    if (!audioStream || !videoStream) {
      setGeneralError("Media stream not ready. Grant access first.");
      return;
    }

    if (!audioWsUrl || !videoWsUrl) {
      setGeneralError(
        "Configure NEXT_PUBLIC_AUDIO_WS_URL and NEXT_PUBLIC_VIDEO_WS_URL environment variables."
      );
      return;
    }

    setGeneralError(null);
    setStreamErrors({ audio: null, video: null });
    setConnectionStates({ audio: "connecting", video: "connecting" });

    const controllerInstance = new StreamingController({
      audioStream,
      videoStream,
      audioUrl: audioWsUrl,
      videoUrl: videoWsUrl,
      token: streamToken || undefined,
      chunkDurationMs: chunkDuration,
      onStatusChange: (kind, state) => {
        setConnectionStates((prev) => ({ ...prev, [kind]: state }));
      },
      onError: (kind, message) => {
        setStreamErrors((prev) => ({ ...prev, [kind]: message }));
      }
    });

    controllerInstance.start();
    setController(controllerInstance);
  }, [audioStream, audioWsUrl, chunkDuration, streamToken, videoStream, videoWsUrl]);

  const handleStopStreaming = useCallback(() => {
    controller?.stop();
    setController(null);
    setConnectionStates({ ...initialConnectionState });
  }, [controller]);

  const isStreaming = controller !== null;
  const disabledReason = useMemo(() => {
    if (permission !== "granted") {
      return "Grant camera & microphone access to start streaming.";
    }
    if (!audioWsUrl || !videoWsUrl) {
      return "Set NEXT_PUBLIC_AUDIO_WS_URL and NEXT_PUBLIC_VIDEO_WS_URL before streaming.";
    }
    return null;
  }, [permission, audioWsUrl, videoWsUrl]);

  const aggregatedError = useMemo(() => {
    const messages = [
      generalError,
      streamErrors.audio ? `Audio: ${streamErrors.audio}` : null,
      streamErrors.video ? `Video: ${streamErrors.video}` : null
    ].filter(Boolean);

    return messages.length ? messages.join(" | ") : null;
  }, [generalError, streamErrors.audio, streamErrors.video]);

  return (
    <main className="page-container">
      <header className="page-header">
        <h1>Real-Time Audio & Video Streaming</h1>
        <p>
          Capture your camera and microphone, preview the feed locally, and stream both
          channels independently to the FastAPI backend in real time.
        </p>
      </header>

      <section className="grid-two">
        <VideoCapture stream={mediaStream} permission={permission} error={permissionError} />

        <div className="panel">
          <div className="panel-heading">
            <h2>Permission & Media Setup</h2>
          </div>

          <div className="permission-content">
            <button
              className="primary-button"
              onClick={requestPermissions}
              disabled={permission === "pending"}
            >
              {permission === "granted" ? "Reinitialize Camera & Mic" : "Enable Camera & Mic"}
            </button>
            <ul className="status-list">
              <li>
                <span className="label">Permissions</span>
                <span className={`status-badge status-${permission}`}>{permission}</span>
              </li>
              <li>
                <span className="label">Video Stream</span>
                <span className={`status-badge ${videoStream ? "status-active" : "status-idle"}`}>
                  {videoStream ? "Available" : "Unavailable"}
                </span>
              </li>
              <li>
                <span className="label">Audio Stream</span>
                <span className={`status-badge ${audioStream ? "status-active" : "status-idle"}`}>
                  {audioStream ? "Available" : "Unavailable"}
                </span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section className="grid-two">
        <AudioVisualizer stream={audioStream} isActive={Boolean(audioStream)} />

        <StreamControls
          permission={permission}
          isStreaming={isStreaming}
          connectionStates={connectionStates}
          onStart={handleStartStreaming}
          onStop={handleStopStreaming}
          disabledReason={disabledReason}
          error={aggregatedError}
        />
      </section>
    </main>
  );
}
