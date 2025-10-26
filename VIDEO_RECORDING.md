# Video Recording & Compilation System

This system allows you to record video and audio streams from the frontend, store them on the backend, and compile them into downloadable MP4 files.

## Features

- **Real-time Recording**: Captures video and audio streams via WebSocket
- **Session Management**: Each recording session gets a unique ID
- **Video Compilation**: Uses FFmpeg to combine video and audio into MP4 files
- **Download Interface**: Frontend UI to compile and download recorded videos
- **Session Cleanup**: Automatic cleanup of old sessions

## Backend API Endpoints

### WebSocket Endpoints
- `ws://localhost:8000/ws/video` - Video stream endpoint
- `ws://localhost:8000/ws/audio` - Audio stream endpoint

### HTTP Endpoints
- `POST /api/compile-video/{session_id}` - Compile a video from session chunks
- `GET /api/download/{session_id}` - Download compiled MP4 file
- `GET /api/sessions` - List all recording sessions
- `DELETE /api/sessions/{session_id}` - Delete a session and its files

## Setup Instructions

### Backend Setup
1. Install dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. Install FFmpeg (required for video compilation):
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt update && sudo apt install ffmpeg`
   - **Windows**: Download from https://ffmpeg.org/download.html

3. Start the backend:
   ```bash
   uvicorn main:app --reload
   ```

### Frontend Setup
1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Set environment variables:
   ```bash
   export NEXT_PUBLIC_VIDEO_WS_URL="ws://localhost:8000/ws/video"
   export NEXT_PUBLIC_AUDIO_WS_URL="ws://localhost:8000/ws/audio"
   ```

3. Start the frontend:
   ```bash
   npm run dev
   ```

## How It Works

1. **Recording**: When you start streaming, the system creates a unique session ID and begins collecting video/audio chunks
2. **Storage**: Chunks are stored in the `recordings/{session_id}/` directory
3. **Compilation**: When you click "Compile Video", FFmpeg combines the video and audio chunks into an MP4 file
4. **Download**: The compiled MP4 can be downloaded directly from the frontend

## File Structure

```
recordings/
├── {session_id_1}/
│   ├── video.webm
│   ├── audio.webm
│   └── {session_id_1}.mp4  # Compiled video
├── {session_id_2}/
│   └── ...
```

## Configuration

- **Storage Directory**: Defaults to `recordings/` (configurable in `video_storage.py`)
- **Session Cleanup**: Sessions older than 24 hours are automatically cleaned up
- **Video Format**: Output is MP4 with H.264 video and AAC audio codecs

## Troubleshooting

### FFmpeg Not Found
If you get FFmpeg errors, ensure FFmpeg is installed and in your PATH:
```bash
ffmpeg -version
```

### Large File Sizes
Video files can be large. Consider implementing:
- Compression settings in FFmpeg
- Chunk size limits
- Storage quotas

### Memory Issues
For long recordings, consider:
- Streaming chunks to disk instead of keeping in memory
- Implementing chunk rotation
- Adding progress indicators for compilation
