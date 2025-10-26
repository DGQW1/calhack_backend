"""Shared dataclasses for slide keyframe processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass(slots=True)
class SlideDetectionParams:
    # Relaxed threshold for real-world video - content must be reasonably stable
    # Lowered from 0.98 to account for webcam noise, compression artifacts, lighting changes
    tau_stable: float = 0.90
    # Change threshold - detect when content significantly changes (slide transition)
    tau_change: float = 0.75
    # Shorter stable duration - 1 second is enough to confirm content is stable
    # Reduced from 2000ms to make detection more responsive
    min_stable_duration_ms: int = 1000
    # Fewer frames to confirm transition - make it more responsive
    # Reduced from 15 to 8 frames (roughly 0.25-0.5 seconds at typical framerates)
    transition_confirm_frames: int = 8
    # Shorter cooldown between slides - allow faster slide changes
    # Reduced from 3000ms to 1500ms for presentations with quick transitions
    cooldown_ms: int = 1500
    # Higher EMA alpha - faster baseline adaptation to handle lighting/movement
    # Increased from 0.08 to adapt more quickly to minor changes
    ema_alpha: float = 0.15
    downscale_width: int = 320
    downscale_height: int = 180
    # Lower threshold for slide change detection - detect moderate content changes
    # Lowered from 0.80 to detect more subtle slide transitions
    slide_change_ssim: float = 0.70
    # Shorter minimum slide duration - 1.5 seconds minimum
    # Reduced from 3000ms to allow capturing shorter slides
    min_slide_duration_ms: int = 1500


@dataclass(slots=True)
class SlideCandidate:
    lecture_id: str
    start_ms: int
    lock_ssim: float
    image_bytes: bytes
    metadata: Dict[str, Any]
    captured_at: Optional[str] = None
    end_ms: Optional[int] = None
    storage_url: Optional[str] = None
    transcript_text: Optional[str] = None
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"kf_{uuid4()}"

    def base_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "lecture_id": self.lecture_id,
            "t_start_ms": self.start_ms,
            "t_end_ms": self.end_ms,
            "storage_url": self.storage_url,
            "score": self.lock_ssim,
        }
        if self.captured_at:
            payload["captured_at"] = self.captured_at
        sequence = self.metadata.get("sequence")
        if sequence is not None:
            payload["sequence"] = sequence
        return payload

