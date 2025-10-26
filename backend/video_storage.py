import asyncio
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiofiles
import ffmpeg

logger = logging.getLogger("backend.video_storage")


class VideoStorage:
    """
    Manages storage and compilation of video/audio chunks from WebSocket streams.
    """
    
    def __init__(self, storage_dir: str = "recordings"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.sessions: Dict[str, "RecordingSession"] = {}
        
    def create_session(self) -> str:
        """Create a new recording session and return its ID."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = RecordingSession(session_id, self.storage_dir)
        logger.info(f"Created recording session: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional["RecordingSession"]:
        """Get a recording session by ID."""
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str) -> None:
        """Remove a recording session and clean up its files."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.cleanup()
            del self.sessions[session_id]
            logger.info(f"Removed recording session: {session_id}")
    
    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> None:
        """Clean up sessions older than max_age_hours."""
        current_time = datetime.now(timezone.utc)
        sessions_to_remove = []
        
        for session_id, session in self.sessions.items():
            if (current_time - session.created_at).total_seconds() > max_age_hours * 3600:
                sessions_to_remove.append(session_id)
        
        for session_id in sessions_to_remove:
            self.remove_session(session_id)


class RecordingSession:
    """
    Manages a single recording session with video and audio chunks.
    """
    
    def __init__(self, session_id: str, storage_dir: Path):
        self.session_id = session_id
        self.storage_dir = storage_dir
        self.created_at = datetime.now(timezone.utc)
        self.video_chunks: List[bytes] = []
        self.audio_chunks: List[bytes] = []
        self.video_metadata: List[Dict] = []
        self.audio_metadata: List[Dict] = []
        self.is_active = True
        self.compiled_file: Optional[Path] = None
        self.final_summary: Optional[str] = None
        self.final_summary_created_at: Optional[datetime] = None
        
        # Create session directory
        self.session_dir = self.storage_dir / session_id
        self.session_dir.mkdir(exist_ok=True)
        self.summary_file = self.session_dir / "summary.json"
        
    async def add_video_chunk(self, chunk: bytes, metadata: Dict) -> None:
        """Add a video chunk to the session."""
        if not self.is_active:
            return
            
        self.video_chunks.append(chunk)
        self.video_metadata.append(metadata)
        logger.info(f"Added video chunk {len(chunk)} bytes to session {self.session_id} (total: {len(self.video_chunks)} chunks)")
    
    async def add_audio_chunk(self, chunk: bytes, metadata: Dict) -> None:
        """Add an audio chunk to the session."""
        if not self.is_active:
            return
            
        self.audio_chunks.append(chunk)
        self.audio_metadata.append(metadata)
        logger.info(f"Added audio chunk {len(chunk)} bytes to session {self.session_id} (total: {len(self.audio_chunks)} chunks)")

    async def save_summary(self, summary: str, created_at: Optional[datetime] = None) -> Optional[Path]:
        """
        Persist the final summary for this session to disk and memory.
        Returns the path to the saved summary file.
        """
        if not summary:
            return None

        self.final_summary = summary
        self.final_summary_created_at = created_at or datetime.now(timezone.utc)

        summary_payload = {
            "session_id": self.session_id,
            "created_at": self.final_summary_created_at.isoformat(),
            "summary": summary,
        }

        async with aiofiles.open(self.summary_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(summary_payload, ensure_ascii=False, indent=2))

        logger.info(f"Saved summary for session {self.session_id} at {self.summary_file}")
        return self.summary_file
    
    async def finalize(self) -> Optional[Path]:
        """
        Finalize the recording by compiling video and audio into an MP4 file.
        Returns the path to the compiled file, or None if compilation fails.
        """
        if not self.is_active:
            return None
            
        self.is_active = False
        
        try:
            logger.info(f"Finalizing session {self.session_id}: {len(self.video_chunks)} video chunks, {len(self.audio_chunks)} audio chunks")
            
            # Save raw chunks to temporary files
            video_file = await self._save_chunks_to_file(self.video_chunks, "video.webm")
            audio_file = await self._save_chunks_to_file(self.audio_chunks, "audio.webm")
            
            if not video_file and not audio_file:
                logger.warning(f"No chunks to save for session {self.session_id}")
                return None
                
            if not video_file:
                logger.warning(f"No video chunks for session {self.session_id}")
            if not audio_file:
                logger.warning(f"No audio chunks for session {self.session_id}")
            
            # Compile into MP4
            output_file = self.session_dir / f"{self.session_id}.mp4"
            success = await self._compile_video(video_file, audio_file, output_file)
            
            if success:
                self.compiled_file = output_file
                logger.info(f"Successfully compiled video for session {self.session_id}: {output_file}")
                return output_file
            else:
                logger.error(f"Failed to compile video for session {self.session_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error finalizing session {self.session_id}: {e}")
            return None
    
    async def _save_chunks_to_file(self, chunks: List[bytes], filename: str) -> Optional[Path]:
        """Save a list of chunks to a file."""
        if not chunks:
            return None
            
        file_path = self.session_dir / filename
        
        try:
            async with aiofiles.open(file_path, 'wb') as f:
                for chunk in chunks:
                    await f.write(chunk)
            return file_path
        except Exception as e:
            logger.error(f"Error saving chunks to {filename}: {e}")
            return None
    
    async def _compile_video(self, video_file: Path, audio_file: Path, output_file: Path) -> bool:
        """Compile video and audio files into an MP4 using ffmpeg."""
        try:
            inputs = []
            
            # Add video input if available
            if video_file and video_file.exists():
                inputs.append(ffmpeg.input(str(video_file)))
            
            # Add audio input if available
            if audio_file and audio_file.exists():
                inputs.append(ffmpeg.input(str(audio_file)))
            
            if not inputs:
                logger.error("No valid input files for compilation")
                return False
            
            # Create output with appropriate codecs
            if len(inputs) == 1:
                # Single input (video or audio only)
                if video_file and video_file.exists():
                    # Video only
                    output = ffmpeg.output(
                        inputs[0],
                        str(output_file),
                        vcodec='libx264',
                        format='mp4'
                    )
                else:
                    # Audio only
                    output = ffmpeg.output(
                        inputs[0],
                        str(output_file),
                        acodec='aac',
                        format='mp4'
                    )
            else:
                # Multiple inputs (video + audio)
                output = ffmpeg.output(
                    inputs[0],
                    inputs[1],
                    str(output_file),
                    vcodec='libx264',
                    acodec='aac',
                    format='mp4',
                    **{'shortest': None}  # End when shortest stream ends
                )
            
            # Run ffmpeg command
            process = await asyncio.create_subprocess_exec(
                *ffmpeg.compile(output, overwrite_output=True),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return False
            
            return output_file.exists()
            
        except Exception as e:
            logger.error(f"Error compiling video with ffmpeg: {e}")
            return False
    
    def cleanup(self) -> None:
        """Clean up session files."""
        try:
            import shutil
            if self.session_dir.exists():
                shutil.rmtree(self.session_dir)
            logger.info(f"Cleaned up session {self.session_id}")
        except Exception as e:
            logger.error(f"Error cleaning up session {self.session_id}: {e}")


# Global video storage instance
video_storage = VideoStorage()
