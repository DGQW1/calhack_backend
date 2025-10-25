"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioVisualizer } from "../components/AudioVisualizer";
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

const connectionStateLabels: Record<StreamConnectionState, string> = {
  idle: "Idle",
  connecting: "Connecting…",
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error"
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

  // Use refs to track latest values for cleanup without triggering re-renders
  const controllerRef = useRef<StreamingController | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);

  const chunkDuration = Number.isNaN(chunkDurationMs) ? undefined : chunkDurationMs;

  // Update refs whenever state changes
  useEffect(() => {
    controllerRef.current = controller;
  }, [controller]);

  useEffect(() => {
    mediaStreamRef.current = mediaStream;
  }, [mediaStream]);

  useEffect(() => {
    const { audio, video } = createMediaStreams(mediaStream);
    setAudioStream(audio);
    setVideoStream(video);
  }, [mediaStream]);

  useEffect(() => {
    return () => {
      // Cleanup on component unmount only - use refs to get latest values
      controllerRef.current?.stop();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []); // Only run cleanup on unmount

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
        video: { facingMode: "environment" },
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
    // Prevent creating multiple controllers
    if (controller) {
      console.warn("Controller already exists, ignoring start request");
      return;
    }

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
  }, [controller, audioStream, audioWsUrl, chunkDuration, streamToken, videoStream, videoWsUrl]);

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

  const blocked = permission !== "granted";
  const primaryAction = isStreaming ? handleStopStreaming : handleStartStreaming;
  const primaryLabel = isStreaming ? "Stop Streaming" : "Start Streaming";
  const primaryDisabled = blocked || (!!disabledReason && !isStreaming);
  const streamingButtonClass = `primary-button ${isStreaming ? "button-stop" : "button-start"}`;

  const permissionButtonLabel =
    permission === "granted" ? "Reinitialize Camera & Mic" : "Enable Camera & Mic";
  const permissionButtonDisabled = permission === "pending";
  const permissionBadgeLabel =
    permission === "granted"
      ? "Ready"
      : permission === "pending"
        ? "Requesting Access"
        : "Permission Needed";

  return (
    <main className="page-container">
      <header className="page-header">
        <h1>Kanting</h1>
        <p>
          Capture your camera and microphone, preview the feed locally, and stream both
          channels independently to the FastAPI backend in real time.
        </p>
      </header>

      <section className="grid-two">
        <VideoCapture stream={mediaStream} permission={permission} error={permissionError} />

        <div className="panel">
          <div className="panel-heading">
            <h2>Control Center</h2>
            <span className={`status-badge status-${permission}`}>{permissionBadgeLabel}</span>
          </div>

          <div className="control-buttons">
            <button
              className="primary-button control-button"
              onClick={requestPermissions}
              disabled={permissionButtonDisabled}
            >
              {permissionButtonLabel}
            </button>
            <button
              className={`${streamingButtonClass} control-button`}
              onClick={primaryAction}
              disabled={primaryDisabled}
            >
              {primaryLabel}
            </button>
          </div>

          {disabledReason && !isStreaming ? <p className="helper-text">{disabledReason}</p> : null}

          <div className="control-status-columns">
            <div className="status-column">
              <h3>Media Sources</h3>
              <ul className="status-list compact">
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
            <div className="status-column connection-status">
              <h3>Connection Status</h3>
              <ul>
                {(["video", "audio"] as StreamKind[]).map((kind) => (
                  <li key={kind}>
                    <span className="label">{kind.toUpperCase()}</span>
                    <span className={`status-badge status-${connectionStates[kind]}`}>
                      {connectionStateLabels[connectionStates[kind]]}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {aggregatedError ? <p className="error-text">{aggregatedError}</p> : null}
        </div>
      </section>

      <section className="grid-two">
        <AudioVisualizer stream={audioStream} isActive={Boolean(audioStream)} />

      </section>
    </main>
  );
}
