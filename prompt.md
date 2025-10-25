# Real-Time Audio/Video Streaming Web Application

## Project Overview
Build a full-stack web application that captures audio and video from a mobile phone's camera and microphone, displays the feed on the frontend, and streams both media streams independently to a backend server in real-time.

## Technology Stack
- **Frontend**: Next.js (React)
- **Backend**: FastAPI (Python)
- **Deployment**: Railway (provides HTTPS by default, accessible from mobile phone)

## Requirements

### Frontend (Next.js)
1. **Media Permissions**
   - Request camera and microphone permissions from the user
   - Handle permission denials gracefully with user-friendly error messages
   - Display appropriate UI states (requesting, granted, denied)

2. **Media Capture**
   - Use WebRTC/MediaRecorder API to capture video and audio
   - Display live video preview to the user
   - Show audio level indicator or waveform visualization
   - Implement start/stop recording controls

3. **Real-Time Streaming**
   - Stream video and audio data **independently** to the backend
   - Use WebSockets or similar real-time protocol
   - Handle connection drops and reconnection logic
   - Display connection status to the user

4. **UI/UX**
   - Responsive design that works well on mobile devices
   - Clean, modern interface
   - Clear visual feedback for recording status
   - Error handling and user notifications

### Backend (FastAPI)
1. **WebSocket Endpoints**
   - Create separate WebSocket endpoints for video and audio streams
   - Accept incoming stream data in real-time
   - Print received data to console (timestamp, data size, stream type)

2. **Data Handling**
   - Accept video stream (likely in WebM, MP4 chunks, or similar format)
   - Accept audio stream (likely in WebM, Opus, or similar format)
   - For now, only print out metadata about received chunks:
     - Timestamp
     - Chunk size
     - Stream type (audio/video)
     - Any other relevant metadata
   - No storage or processing required at this stage

3. **CORS & Security**
   - Configure CORS properly for cross-origin requests
   - Handle WebSocket connections securely
   - Implement basic connection validation

### Streaming Architecture
- **Independent Streams**: Audio and video must be sent via separate connections/channels
- **Real-Time**: Minimize latency between capture and backend receipt
- **Format**: Use web-compatible codecs (WebM with VP8/VP9 for video, Opus for audio recommended)
- **Chunking**: Send data in manageable chunks (e.g., 100ms - 1s intervals)

### Deployment Requirements
1. **HTTPS**: Required for camera/microphone access in browsers (Railway provides this automatically)
2. **Mobile Access**: Backend and frontend must be accessible from mobile phone
3. **Platform**: Railway for both frontend and backend deployment
4. **Configuration Files**: Include all necessary Railway configuration files (Procfile, railway.json, etc.)

**IMPORTANT**: Provide complete, step-by-step Railway deployment instructions including:
- How to set up Railway account and projects
- How to configure both frontend and backend services
- Environment variables setup
- How to obtain and use the deployed URLs on mobile phone
- Troubleshooting common deployment issues

### Development Priorities
1. Set up basic Next.js frontend with camera/microphone access
2. Implement video preview and audio visualization
3. Set up FastAPI backend with WebSocket support
4. Implement independent streaming for audio and video
5. Add connection status and error handling
6. Test on mobile device
7. Deploy with HTTPS

### Nice-to-Have Features
- Recording duration display
- Data rate indicator (KB/s)
- Network quality indicator
- Audio mute toggle while video continues

### Testing Checklist
- [ ] Camera permission request works on mobile
- [ ] Microphone permission request works on mobile
- [ ] Video preview displays correctly on mobile
- [ ] Audio levels are visible
- [ ] Backend receives video stream data
- [ ] Backend receives audio stream data
- [ ] Streams are independent (can process separately)
- [ ] Console shows real-time data reception
- [ ] Reconnection works after network interruption
- [ ] Works over HTTPS from mobile phone

## Technical Notes
- Use `navigator.mediaDevices.getUserMedia()` for media access
- Consider using MediaRecorder API with separate streams
- WebSocket is preferred over HTTP polling for real-time streaming
- Remember that mobile browsers require HTTPS for camera/microphone access
- Test with actual mobile device, not just browser dev tools

## File Structure Suggestion
```
calhack_backend/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── requirements.txt     # Python dependencies
│   ├── Procfile             # Railway process file
│   ├── railway.json         # Railway configuration (optional)
│   └── websocket_handlers.py
├── frontend/
│   ├── app/
│   │   ├── page.tsx         # Main page with camera UI
│   │   └── layout.tsx
│   ├── components/
│   │   ├── VideoCapture.tsx
│   │   ├── AudioVisualizer.tsx
│   │   └── StreamControls.tsx
│   ├── lib/
│   │   └── websocket.ts     # WebSocket client logic
│   ├── package.json
│   ├── next.config.js
│   └── .env.local           # Local environment variables (Railway URLs)
└── README.md
```

## Getting Started
Please implement this project step by step:

1. Set up basic FastAPI backend with WebSocket support
2. Set up Next.js frontend with camera/microphone access
3. Implement video preview and audio visualization
4. Implement independent streaming for audio and video
5. Add connection status and error handling
6. Test locally
7. **Provide complete Railway deployment instructions**
8. Test on mobile device with Railway URLs

## Deployment Instructions Required
**Please provide the full, detailed instructions on how to deploy this application to Railway**, including:

1. **Railway Setup**
   - Creating Railway account
   - Setting up new project
   - Connecting GitHub repository (if applicable)

2. **Backend Deployment**
   - Configuring the FastAPI service on Railway
   - Setting root directory and build settings
   - Required environment variables
   - Start command configuration
   - How to access backend logs

3. **Frontend Deployment**
   - Configuring the Next.js service on Railway
   - Setting root directory and build settings
   - Environment variables (backend URL, WebSocket URL)
   - Next.js configuration for Railway

4. **Connecting Frontend to Backend**
   - How to get the Railway-generated URLs
   - How to set up WebSocket connections (wss://)
   - CORS configuration

5. **Testing on Mobile**
   - How to access the deployed app from a mobile phone
   - Verifying HTTPS is working
   - Checking permissions and streaming functionality

6. **Monitoring and Debugging**
   - How to view logs on Railway
   - Common issues and solutions
   - How to restart services if needed

Include all necessary configuration files (Procfile, railway.json, environment variable examples, etc.)
