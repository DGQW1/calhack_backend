"use client";

import { useEffect, useRef } from "react";

export type PermissionState = "idle" | "pending" | "granted" | "denied";

interface VideoCaptureProps {
  stream: MediaStream | null;
  permission: PermissionState;
  error?: string | null;
}

const statusCopy: Record<PermissionState, string> = {
  idle: "Awaiting permission request",
  pending: "Requesting camera & microphone access…",
  granted: "Camera & microphone ready",
  denied: "Permission denied"
};

export function VideoCapture({ stream, permission, error }: VideoCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const videoEl = videoRef.current;
    if (!videoEl) {
      return;
    }

    if (stream) {
      videoEl.srcObject = stream;
      const play = async () => {
        try {
          await videoEl.play();
        } catch (err) {
          // Browser might block autoplay; keep muted preview visible
          console.warn("Unable to autoplay video preview:", err);
        }
      };

      play();
    } else {
      videoEl.srcObject = null;
    }

    return () => {
      if (videoEl) {
        videoEl.srcObject = null;
      }
    };
  }, [stream]);

  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>Live Camera Preview</h2>
        <span className={`status-badge status-${permission}`}>
          {statusCopy[permission]}
        </span>
      </div>

      <div className="video-container">
        {stream ? (
          <video
            ref={videoRef}
            className="video-preview"
            muted
            autoPlay
            playsInline
          />
        ) : (
          <div className="video-placeholder">
            <span role="img" aria-label="camera">
              🎥
            </span>
            <p>Grant access to see your live camera preview here.</p>
          </div>
        )}
      </div>

      {error ? <p className="error-text">{error}</p> : null}
    </div>
  );
}
