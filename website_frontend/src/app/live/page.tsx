'use client';

import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { usePageTitle } from '@/lib/PageTitleContext';
import Image from 'next/image';

// --- Inline SVG Icons ---
const IconCheck = ({ className }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

// // NOTE: IconCamera is no longer used by the main component but kept for modal
// const IconCamera = ({ className }: { className?: string }) => (
//   <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
//     <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
//     <circle cx="12" cy="13" r="3" />
//   </svg>
// );

// const IconMic = ({ className }: { className?: string }) => (
//   <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
//     <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
//     <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
//     <line x1="12" x2="12" y1="19" y2="22" />
//   </svg>
// );

const IconWifi = ({ className }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M5 12.55a11 11 0 0 1 14.08 0" />
      <path d="M1.42 9a16 16 0 0 1 21.16 0" />
      <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
      <line x1="12" x2="12.01" y1="20" y2="20" />
    </svg>
);

const IconWifiOff = ({ className }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <line x1="1" x2="23" y1="1" y2="23" />
      <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
      <path d="M5 12.55a11 11 0 0 1 5.17-2.39" />
      <path d="M10.71 5.05A16 16 0 0 1 22.58 9" />
      <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
      <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
      <line x1="12" x2="12.01" y1="20" y2="20" />
    </svg>
);
// --- End SVG Icons ---

// A simple in-page modal component
const Modal = ({ message, onClose }: { message: string, onClose: () => void }) => (
  <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div className="bg-white p-6 rounded-lg shadow-xl max-w-sm w-full text-center">
      <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100">
        <IconCheck className="h-6 w-6 text-green-600" />
      </div>
      <h3 className="text-lg leading-6 font-medium text-gray-900 mt-4">Success</h3>
      <p className="text-sm text-gray-500 mt-2">{message}</p>
      <button
        onClick={onClose}
        className="mt-6 w-full bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700"
      >
        Close
      </button>
    </div>
  </div>
);

type SlideEntry = {
  id: string;
  url: string;
  sessionId: string;
  capturedAt?: string | null;
  storageKey?: string | null;
};

const KEYFRAME_HISTORY_LIMIT = 24;

/**
 * This component now acts as a "viewer" or "listener".
 * It connects to the backend and ONLY receives transcript updates.
 */
export default function App() {
  const { setPageTitle } = usePageTitle();
  const webSocketRef = useRef<WebSocket | null>(null);
  const keyframesSocketRef = useRef<WebSocket | null>(null);
  const transcriptContainerRef = useRef<HTMLDivElement | null>(null);
  const wasConnectedRef = useRef(false);
  const activeSessionIdRef = useRef<string | null>(null);

  const [isConnected, setIsConnected] = useState(false);
  const [transcription, setTranscription] = useState('');
  const [interimText, setInterimText] = useState('');
  const [modalMessage, setModalMessage] = useState<string | null>(null);

  const [screenshots, setScreenshots] = useState<SlideEntry[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // --- WebSocket Connection Logic ---
  const summaryWsUrl = process.env.NEXT_PUBLIC_SUMMARY_WS_URL || 'ws://localhost:8000/ws/summary';
  const keyframesWsUrl = process.env.NEXT_PUBLIC_KEYFRAMES_WS_URL || 'ws://localhost:8000/ws/keyframes';
  const apiBaseUrl = useMemo(() => {
    const envBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
    if (envBase) {
      return envBase.replace(/\/+$/, '');
    }
    if (!summaryWsUrl) {
      return null;
    }
    try {
      const ws = new URL(summaryWsUrl);
      ws.protocol = ws.protocol === 'wss:' ? 'https:' : 'http:';
      ws.pathname = '';
      ws.search = '';
      ws.hash = '';
      return ws.toString().replace(/\/+$/, '');
    } catch {
      return null;
    }
  }, [summaryWsUrl]);

  const slidesBaseUrl = useMemo(() => {
    const envBase = process.env.NEXT_PUBLIC_SLIDES_BASE_URL?.trim();
    if (envBase) {
      return envBase.replace(/\/+$/, '');
    }
    if (!keyframesWsUrl) {
      return null;
    }
    try {
      const ws = new URL(keyframesWsUrl);
      ws.protocol = ws.protocol === 'wss:' ? 'https:' : 'http:';
      ws.pathname = '/slides';
      ws.search = '';
      ws.hash = '';
      return ws.toString().replace(/\/+$/, '');
    } catch {
      return null;
    }
  }, [keyframesWsUrl]);

  const resolveKeyframeUrl = useCallback(
    (rawUrl: string | null | undefined) => {
      if (!rawUrl) {
        return null;
      }
      if (/^https?:\/\//i.test(rawUrl)) {
        return rawUrl;
      }
      if (rawUrl.startsWith('file://')) {
        if (!slidesBaseUrl) {
          return null;
        }
        const normalized = rawUrl.replace(/\\/g, '/');
        const idx = normalized.toLowerCase().lastIndexOf('/slide_storage/');
        if (idx !== -1) {
          const key = normalized.slice(idx + '/slide_storage/'.length);
          if (key) {
            return `${slidesBaseUrl}/${key}`;
          }
        }
        return null;
      }
      if (rawUrl.startsWith('/slides/')) {
        if (!slidesBaseUrl) {
          return null;
        }
        return `${slidesBaseUrl}${rawUrl}`;
      }
      if (slidesBaseUrl && !rawUrl.includes('://')) {
        return `${slidesBaseUrl}/${rawUrl.replace(/^\/+/, '')}`;
      }
      return rawUrl;
    },
    [slidesBaseUrl]
  );

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const loadSlides = useCallback(
    async (sessionId: string) => {
      if (!apiBaseUrl) {
        return;
      }
      try {
        const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/slides`);
        if (!response.ok) {
          throw new Error(`Failed to load slides for session ${sessionId}: ${response.status}`);
        }
        const body = await response.json();
        const entries: SlideEntry[] = [];
        if (Array.isArray(body?.slides)) {
          for (const item of body.slides) {
            if (!item) {
              continue;
            }
            const storageUrl = typeof item.storage_url === 'string' ? item.storage_url : null;
            const storageKey = typeof item.storage_key === 'string' ? item.storage_key : null;
            const resolved = resolveKeyframeUrl(storageUrl);
            if (!resolved) {
              continue;
            }
            entries.push({
              id: storageKey || resolved,
              url: resolved,
              sessionId,
              storageKey,
            });
          }
        }
        if (activeSessionIdRef.current === sessionId) {
          setScreenshots(entries.slice(0, KEYFRAME_HISTORY_LIMIT));
        }
      } catch (error) {
        console.error('Unable to fetch slides for session:', error);
      }
    },
    [apiBaseUrl, resolveKeyframeUrl]
  );

  const fetchActiveSession = useCallback(async () => {
    if (!apiBaseUrl) {
      return;
    }
    try {
      const response = await fetch(`${apiBaseUrl}/api/sessions`);
      if (!response.ok) {
        throw new Error(`Failed to query sessions: ${response.status}`);
      }
      const body = await response.json();
      const sessions = Array.isArray(body?.sessions) ? body.sessions : [];
      const active =
        sessions.find((session: any) => session && session.is_active) ?? sessions[0];
      if (active?.session_id && active.session_id !== activeSessionIdRef.current) {
        activeSessionIdRef.current = active.session_id;
        setActiveSessionId(active.session_id);
        setScreenshots([]);
      }
    } catch (error) {
      console.error('Unable to fetch sessions list:', error);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchActiveSession();
  }, [fetchActiveSession]);

  useEffect(() => {
    if (!activeSessionId) {
      setScreenshots([]);
      return;
    }
    setScreenshots([]);
    void loadSlides(activeSessionId);
  }, [activeSessionId, loadSlides]);

  const connectWebSocket = useCallback(() => {
    // Disconnect if already connected
    if (webSocketRef.current) {
      webSocketRef.current.close();
    }

    if (!summaryWsUrl) {
      console.error('NEXT_PUBLIC_SUMMARY_WS_URL is not configured.');
      setInterimText('[CONFIGURATION ERROR]');
      return;
    }

    const ws = new WebSocket(summaryWsUrl);
    webSocketRef.current = ws;

    ws.onopen = () => {
      console.log('Connected to backend transcript server.');
      setIsConnected(true);
      wasConnectedRef.current = true;
      setTranscription('');
      setInterimText('Waiting for summary updates...');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'summary') {
          const summaryText = typeof data.summary === 'string' ? data.summary : '';
          const updatedAt = data.created_at ? new Date(data.created_at) : null;

          setTranscription(summaryText);
          setInterimText(updatedAt ? `Last updated at ${updatedAt.toLocaleTimeString()}` : '');

          // Auto scroll to latest summary
          requestAnimationFrame(() => {
            const container = transcriptContainerRef.current;
            if (container) {
              container.scrollTop = container.scrollHeight;
            }
          });
        }
      } catch (e) {
        console.error("Error parsing WebSocket message:", e);
      }
    };

    ws.onerror = (e) => {
      console.error('WebSocket Error:', e);
      setInterimText('[CONNECTION ERROR]');
      setIsConnected(false);
    };

    ws.onclose = () => {
      console.log('WebSocket closed.');
      if (wasConnectedRef.current) { // Only show disconnected if it was previously connected
        setInterimText('Disconnected from stream.');
      }
      setIsConnected(false);
      wasConnectedRef.current = false;
    };
  }, [summaryWsUrl]);

  useEffect(() => {
    if (!keyframesWsUrl) {
      console.error('NEXT_PUBLIC_KEYFRAMES_WS_URL is not configured.');
      return;
    }

    const ws = new WebSocket(keyframesWsUrl);
    keyframesSocketRef.current = ws;

    ws.onopen = () => {
      console.log('Connected to backend keyframe server.');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type !== 'keyframe_detected') {
          return;
        }

        const sessionId = typeof data.session_id === 'string' ? data.session_id : null;
        const storageUrl = typeof data.storage_url === 'string' ? data.storage_url : null;
        const storageKey = typeof data.storage_key === 'string' ? data.storage_key : null;
        const resolvedUrl = resolveKeyframeUrl(storageUrl);
        const capturedAt = typeof data.captured_at === 'string' ? data.captured_at : null;
        let keyframeId = typeof data.id === 'string' && data.id ? data.id : null;

        if (!sessionId) {
          console.warn('Received keyframe without session_id, ignoring.');
          return;
        }

        if (!resolvedUrl) {
          console.warn('Unable to resolve keyframe storage URL:', storageUrl);
          return;
        }

        if (!keyframeId) {
          keyframeId = storageKey || `${sessionId}-${resolvedUrl}`;
        }

        const currentActive = activeSessionIdRef.current;
        if (currentActive !== sessionId) {
          activeSessionIdRef.current = sessionId;
          setActiveSessionId(sessionId);
          setScreenshots([]);
        }

        if (activeSessionIdRef.current !== sessionId) {
          return;
        }

        setScreenshots((prev) => {
          const filtered = prev.filter((item) => item.id !== keyframeId);
          const nextEntry: SlideEntry = {
            id: keyframeId!,
            url: resolvedUrl,
            sessionId,
            capturedAt,
            storageKey,
          };
          return [nextEntry, ...filtered].slice(0, KEYFRAME_HISTORY_LIMIT);
        });
      } catch (error) {
        console.error('Error parsing keyframe WebSocket message:', error);
      }
    };

    ws.onerror = (event) => {
      console.error('Keyframe WebSocket Error:', event);
    };

    ws.onclose = () => {
      console.log('Keyframe WebSocket closed.');
      keyframesSocketRef.current = null;
    };

    return () => {
      keyframesSocketRef.current = null;
      ws.close();
    };
  }, [keyframesWsUrl, resolveKeyframeUrl]);

  // Connect on mount and handle cleanup
  useEffect(() => {
    setPageTitle('Live Recording'); // Set the page title
    connectWebSocket(); // Connect when component loads

    return () => {
      webSocketRef.current?.close(); // Disconnect on unmount
      keyframesSocketRef.current?.close();
    };
  }, [connectWebSocket, setPageTitle]);

  return (
    <div className="p-6 md:p-10 space-y-6 bg-gray-50 min-h-screen">
      {modalMessage && <Modal message={modalMessage} onClose={() => setModalMessage(null)} />}
      
      {/* Main Content Area: Key Visuals and Transcription */}
      <div className="flex flex-col lg:flex-row gap-6">
        
        {/* Left Column: Key Visuals */}
        <div className="flex-1 space-y-4">
          <h2 className="text-2xl font-semibold text-gray-800">Key Visuals</h2>
          <p className="text-sm text-gray-500">
            {activeSessionId ? `Showing slides for session ${activeSessionId}` : 'Waiting for an active session…'}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {screenshots.length > 0 ? (
              screenshots.map(({ id, url }) => (
                <div key={id} className="relative aspect-video bg-gray-200 rounded-lg overflow-hidden shadow-sm">
                  <Image
                    src={url}
                    alt="Detected slide keyframe"
                    fill
                    className="object-cover"
                    unoptimized
                  />
                </div>
              ))
            ) : (
              <p className="text-gray-500 col-span-full">
                {activeSessionId ? 'No key visuals captured for this session yet.' : 'Start streaming to capture key visuals.'}
              </p>
            )}
          </div>
        </div>

        {/* Right Column: Live Transcription */}
        <div className="w-full lg:w-full lg:max-w-sm space-y-4">
          <h2 className="text-2xl font-semibold text-gray-800">Live Transcription</h2>
          
          {/* Connection Status Button */}
          <button
            onClick={connectWebSocket} // Re-connect if disconnected
            className={`flex items-center justify-center gap-2 px-5 py-3 rounded-md font-medium text-white shadow-sm transition-colors w-full
              ${isConnected ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}`}
          >
            {isConnected ? <IconWifi className="w-5 h-5" /> : <IconWifiOff className="w-5 h-5" />}
            {isConnected ? 'Connected to Stream' : 'Disconnected (Click to Reconnect)'}
          </button>
          
          {/* Transcription Output */}
          <div
            ref={transcriptContainerRef}
            className="w-full bg-white p-4 rounded-lg shadow-md border border-gray-200 h-[400px] lg:h-[calc(100vh-270px)] overflow-y-auto"
          >
            <p className="text-gray-700 whitespace-pre-wrap">
              {/* Display the accumulated final text */}
              {transcription}

              {/* Display the current, non-final (interim) text */}
              <span className="block text-gray-400 italic mt-2">
                {interimText}
              </span>
            </p>
          </div>
        </div>
      </div>

    </div>
  );
}
