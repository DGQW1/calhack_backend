"use client";

import { useCallback, useEffect, useState } from "react";

interface VideoRecorderProps {
  isStreaming: boolean;
  connectionStates: {
    audio: string;
    video: string;
  };
  onSessionIdReceived?: (sessionId: string) => void;
}

interface Session {
  session_id: string;
  created_at: string;
  is_active: boolean;
  has_compiled_file: boolean;
  video_chunks: number;
  audio_chunks: number;
}

export function VideoRecorder({ isStreaming, connectionStates, onSessionIdReceived }: VideoRecorderProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch sessions from the backend
  const fetchSessions = useCallback(async () => {
    try {
      const response = await fetch("/api/sessions");
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions);
      }
    } catch (err) {
      console.error("Failed to fetch sessions:", err);
    }
  }, []);

  // Compile video for a session
  const compileVideo = useCallback(async (sessionId: string) => {
    setCompiling(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/compile-video/${sessionId}`, {
        method: "POST",
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log("Video compilation:", data);
        await fetchSessions(); // Refresh sessions list
      } else {
        const errorData = await response.json();
        setError(errorData.detail || "Failed to compile video");
      }
    } catch (err) {
      setError("Failed to compile video");
      console.error("Compilation error:", err);
    } finally {
      setCompiling(false);
    }
  }, [fetchSessions]);

  // Download video
  const downloadVideo = useCallback((sessionId: string) => {
    const downloadUrl = `/api/download/${sessionId}`;
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `recording_${sessionId}.mp4`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, []);

  // Delete session
  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      const response = await fetch(`/api/sessions/${sessionId}`, {
        method: "DELETE",
      });
      
      if (response.ok) {
        await fetchSessions(); // Refresh sessions list
      } else {
        const errorData = await response.json();
        setError(errorData.detail || "Failed to delete session");
      }
    } catch (err) {
      setError("Failed to delete session");
      console.error("Delete error:", err);
    }
  }, [fetchSessions]);

  // Listen for session ID from WebSocket messages
  useEffect(() => {
    const handleSessionIdReceived = (event: CustomEvent) => {
      const { sessionId, streamType } = event.detail;
      if (streamType === "video" || streamType === "audio") {
        setCurrentSessionId(sessionId);
        onSessionIdReceived?.(sessionId);
      }
    };

    // Listen for custom session ID events
    window.addEventListener("sessionIdReceived", handleSessionIdReceived as EventListener);
    return () => window.removeEventListener("sessionIdReceived", handleSessionIdReceived as EventListener);
  }, [onSessionIdReceived]);

  // Fetch sessions on mount and when streaming stops
  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  useEffect(() => {
    if (!isStreaming) {
      // When streaming stops, refresh sessions to show the new recording
      setTimeout(fetchSessions, 1000);
    }
  }, [isStreaming, fetchSessions]);

  const isRecording = isStreaming && connectionStates.audio === "connected" && connectionStates.video === "connected";

  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>Video Recording</h2>
        <span className={`status-badge ${isRecording ? "status-active" : "status-idle"}`}>
          {isRecording ? "Recording" : "Idle"}
        </span>
      </div>

      {currentSessionId && (
        <div className="current-session">
          <h3>Current Session</h3>
          <p className="session-id">ID: {currentSessionId}</p>
          <div className="session-actions">
            <button
              className="primary-button"
              onClick={() => compileVideo(currentSessionId)}
              disabled={compiling}
            >
              {compiling ? "Compiling..." : "Compile Video"}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="error-message">
          <p>{error}</p>
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      <div className="sessions-list">
        <h3>Recorded Sessions</h3>
        {sessions.length === 0 ? (
          <p className="no-sessions">No recorded sessions yet</p>
        ) : (
          <div className="sessions-grid">
            {sessions.map((session) => (
              <div key={session.session_id} className="session-card">
                <div className="session-info">
                  <h4>Session {session.session_id.slice(0, 8)}...</h4>
                  <p className="session-date">
                    {new Date(session.created_at).toLocaleString()}
                  </p>
                  <div className="session-stats">
                    <span>Video: {session.video_chunks} chunks</span>
                    <span>Audio: {session.audio_chunks} chunks</span>
                  </div>
                </div>
                <div className="session-actions">
                  {session.has_compiled_file ? (
                    <button
                      className="primary-button button-download"
                      onClick={() => downloadVideo(session.session_id)}
                    >
                      Download MP4
                    </button>
                  ) : (
                    <button
                      className="primary-button"
                      onClick={() => compileVideo(session.session_id)}
                      disabled={compiling}
                    >
                      {compiling ? "Compiling..." : "Compile"}
                    </button>
                  )}
                  <button
                    className="primary-button button-delete"
                    onClick={() => deleteSession(session.session_id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
