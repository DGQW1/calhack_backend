"use client";

import type { PermissionState } from "./VideoCapture";
import type { StreamConnectionState, StreamKind } from "../lib/websocket";

interface StreamControlsProps {
  permission: PermissionState;
  isStreaming: boolean;
  connectionStates: Record<StreamKind, StreamConnectionState>;
  onStart: () => void;
  onStop: () => void;
  disabledReason?: string | null;
  error?: string | null;
}

const stateLabels: Record<StreamConnectionState, string> = {
  idle: "Idle",
  connecting: "Connecting…",
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error"
};

export function StreamControls({
  permission,
  isStreaming,
  connectionStates,
  onStart,
  onStop,
  disabledReason,
  error
}: StreamControlsProps) {
  const blocked = permission !== "granted";

  const primaryAction = isStreaming ? onStop : onStart;
  const primaryLabel = isStreaming ? "Stop Streaming" : "Start Streaming";
  const primaryDisabled = blocked || (!!disabledReason && !isStreaming);

  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>Streaming Controls</h2>
        <span className={`status-badge status-${permission}`}>
          {permission === "granted" ? "Ready" : "Permission required"}
        </span>
      </div>

      <div className="controls-grid">
        <button
          className={`primary-button ${isStreaming ? "button-stop" : "button-start"}`}
          onClick={primaryAction}
          disabled={primaryDisabled}
        >
          {primaryLabel}
        </button>

        {disabledReason && !isStreaming ? (
          <p className="helper-text">{disabledReason}</p>
        ) : null}

        <div className="connection-status">
          <h3>Connection Status</h3>
          <ul>
            {(["video", "audio"] as StreamKind[]).map((kind) => (
              <li key={kind}>
                <span className="label">{kind.toUpperCase()}</span>
                <span className={`status-badge status-${connectionStates[kind]}`}>
                  {stateLabels[connectionStates[kind]]}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
    </div>
  );
}
