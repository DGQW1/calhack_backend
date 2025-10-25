# Real-Time Audio/Video Streaming Web Application

A full-stack demo that captures audio and video from a mobile browser, previews the feed locally, and streams both channels independently to a FastAPI backend over WebSockets. The project is split into a Next.js frontend (`frontend/`) and a FastAPI backend (`backend/`).

## Repository Structure

```
.
├── backend/                 # FastAPI WebSocket server
│   ├── main.py
│   ├── websocket_handlers.py
│   ├── requirements.txt
│   └── Procfile
├── frontend/                # Next.js 14 app router project
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── package.json
│   ├── next.config.js
│   ├── Procfile
│   └── .env.local.example
├── railway.json             # Multi-service deployment template for Railway CLI
├── prompt.md
└── README.md
```

## Prerequisites

- Node.js 18+ (Next.js 14 requires >= 18.17.0; Node 20 LTS recommended)
- Python 3.11+ (for FastAPI)
- `ffmpeg` is **not** required; streaming uses the browser `MediaRecorder` API.

## Local Development

### 1. Backend (FastAPI)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: guard WebSocket access with a shared token
export STREAMING_ACCESS_TOKEN=supersecret

# Optional: lock down CORS origins ("*" by default)
export CORS_ALLOW_ORIGINS=https://localhost:3000

# Start the server (we're already in backend/ directory, so use main:app)
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Key endpoints:
- `ws://localhost:8000/ws/video` – receives binary & text chunks for the video stream
- `ws://localhost:8000/ws/audio` – receives binary & text chunks for the audio stream
- `GET /health` – simple readiness probe

### 2. Frontend (Next.js)

```bash
cd frontend
# Ensure your Node runtime is >= 18.17 (Node 20 LTS shown here)
nvm install 20 >/dev/null 2>&1 || true
nvm use 20 || echo "Use your preferred version manager to select Node >= 18.17"
cp .env.local.example .env.local
# Update the WebSocket URLs in .env.local to point at your backend service

npm install
npm run dev
```

Visit http://localhost:3000 on a desktop browser to verify the UI. For mobile testing, use the deployed Railway URLs (HTTPS is required for camera/mic access).

## Streaming Flow

1. User grants camera & microphone access. The UI previews the video stream and renders a live audio level meter driven by the Web Audio API.
2. Clicking **Start Streaming** instantiates a `StreamingController` that:
   - Opens independent WebSocket connections for audio and video.
   - Starts dedicated `MediaRecorder` instances for each track.
   - Sends JSON metadata followed by binary chunks on a fixed interval (default 1000 ms).
   - Transparently reconnects sockets if they drop while continuing to record.
3. The FastAPI backend validates the optional shared token, accepts the connection, and logs timestamped metadata for every chunk (size, stream type, MIME type, sequence number).

## Testing Checklist

- [ ] Camera permission request succeeds on mobile browsers.
- [ ] Microphone permission request succeeds on mobile browsers.
- [ ] Live video preview renders after permission grant.
- [ ] Audio visualization reacts to input volume.
- [ ] Backend console logs show incoming video chunks.
- [ ] Backend console logs show incoming audio chunks.
- [ ] Audio and video streams operate on independent WebSocket connections.
- [ ] Connection status indicators react to network interruptions and reconnections.
- [ ] Application works end-to-end over HTTPS from a mobile device.

## Railway Deployment (Step by Step)

These steps assume you already pushed the repository to GitHub.

### 1. Railway Account & Project

1. Sign in or create an account at https://railway.app.
2. Create a **new project** (e.g., `calhack-realtime-streaming`).
3. Connect your GitHub account when prompted, then select the repository containing this codebase.

> **Tip:** If you prefer the Railway CLI, `railway up` can read the provided `railway.json` template. Review the file and adjust fields (builder, commands, domains) to match the current CLI schema.

### 2. Backend Service (FastAPI)

1. Inside the project, add a new **service** and choose the repository you just linked.
2. Set the service root to `backend/`.
3. Build options:
   - Builder: **Nixpacks** (default)
   - Install command: `pip install -r requirements.txt` (since service root is `backend/`)
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Environment variables:
   - `STREAMING_ACCESS_TOKEN` (optional) – shared secret checked by the backend.
   - `CORS_ALLOW_ORIGINS` – CSV list of allowed origins (e.g., `https://your-frontend.up.railway.app`).
6. Deploy and wait for the build to finish.
7. After deployment, capture the generated HTTPS domain, e.g. `https://calhack-backend-production.up.railway.app`.
8. Verify with `railway logs` or the dashboard log viewer that the service is running and health checks pass (`GET /health`).

### 3. Frontend Service (Next.js)

1. Add another service from the same repository.
2. Set the root to `frontend/`.
3. Build options:
   - Builder: **Nixpacks** (or Node.js)
   - Install command: `npm install`
   - Build command: `npm run build`
4. Start command: `npm run start`
5. Environment variables:
   - `NEXT_PUBLIC_AUDIO_WS_URL` – e.g., `wss://calhack-backend-production.up.railway.app/ws/audio`
   - `NEXT_PUBLIC_VIDEO_WS_URL` – e.g., `wss://calhack-backend-production.up.railway.app/ws/video`
   - `NEXT_PUBLIC_STREAM_TOKEN` (optional) – must match the backend token if one is set.
   - `NEXT_PUBLIC_CHUNK_DURATION_MS` (optional) – override chunk duration if needed.
6. Redeploy the frontend. Once live, note the public HTTPS domain (e.g., `https://calhack-frontend-production.up.railway.app`).

### 4. Connect Frontend & Backend

1. Confirm the backend domain uses HTTPS. Railway supplies valid certificates automatically.
2. Update the frontend environment variables if the backend URL changes and redeploy.
3. On the backend, ensure `CORS_ALLOW_ORIGINS` includes the **frontend** origin and any local development origins you still require.
4. If you enforce `STREAMING_ACCESS_TOKEN`, provide the token to both the backend (exact value) and frontend (`NEXT_PUBLIC_STREAM_TOKEN`). The frontend automatically appends `?token=...` when opening sockets.

### 5. Mobile Testing Over HTTPS

1. Open the **frontend Railway URL** on your phone.
2. Grant camera/microphone permissions when prompted (flags may appear differently on iOS and Android).
3. Start streaming and monitor the backend logs to confirm real-time chunk reception.
4. If the preview or streaming fails:
   - Confirm the page origin is HTTPS.
   - Check the console logs via browser dev tools (Android: Chrome Remote Debugging, iOS: Safari Web Inspector).
   - Verify environment variables are configured on Railway.

### 6. Monitoring & Operations

- **Logs:** Use the Railway dashboard or `railway logs --service <service-name>` to tail logs in real time.
- **Restarts:** `railway redeploy --service <service-name>` restarts a service with the latest code.
- **Common Issues:**
  - *Media permission blocked:* Ensure the site uses HTTPS and that the user’s browser has not permanently denied access.
  - *WebSocket fails to connect:* Check that the backend domain and token values are correct. The frontend logs a descriptive error badge when connections fail.
  - *CORS errors:* Verify `CORS_ALLOW_ORIGINS` includes both the frontend Railway domain and any local development origins.

## Next Steps

- Consider persisting streams (e.g., to S3 or WebRTC SFU) once the pipeline is stable.
- Add automated tests for the `StreamingController` (mocking `MediaRecorder` and `WebSocket`).
- Expand UI to include data rates, duration indicators, and manual reconnection controls.

Happy streaming!
