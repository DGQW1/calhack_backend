"use client";

import { useEffect, useRef, useState } from "react";

interface AudioVisualizerProps {
  stream: MediaStream | null;
  isActive: boolean;
}

const MIN_DECIBELS = -90;
const MAX_DECIBELS = -10;

export function AudioVisualizer({ stream, isActive }: AudioVisualizerProps) {
  const [level, setLevel] = useState(0);
  const animationRef = useRef<number>();

  useEffect(() => {
    if (!stream) {
      setLevel(0);
      return;
    }

    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.6;
    analyser.minDecibels = MIN_DECIBELS;
    analyser.maxDecibels = MAX_DECIBELS;
    source.connect(analyser);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const updateLevel = async () => {
      if (audioContext.state === "suspended") {
        try {
          await audioContext.resume();
        } catch (error) {
          console.warn("Unable to resume AudioContext:", error);
        }
      }

      analyser.getByteFrequencyData(dataArray);
      const sum = dataArray.reduce((acc, value) => acc + value, 0);
      const average = sum / dataArray.length;
      setLevel(Math.round((average / 255) * 100));

      animationRef.current = requestAnimationFrame(updateLevel);
    };

    updateLevel();

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      source.disconnect();
      analyser.disconnect();
      audioContext.close().catch((error) => {
        console.warn("Failed to close AudioContext cleanly:", error);
      });
    };
  }, [stream]);

  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>Audio Level</h2>
        <span className={`status-badge ${isActive ? "status-active" : "status-idle"}`}>
          {isActive ? "Monitoring" : "Idle"}
        </span>
      </div>

      <div className="audio-meter">
        <div
          className="audio-meter-fill"
          style={{ width: `${isActive ? level : 0}%` }}
        />
      </div>
      <p className="audio-meter-label">Current level: {isActive ? level : 0}%</p>
    </div>
  );
}
