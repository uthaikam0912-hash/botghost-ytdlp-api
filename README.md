# BotGhost Video API

Flask API for starting a YouTube download job, checking its status, and retrieving the resulting file. Only use it for videos you own or have permission to download, and follow YouTube's terms and applicable law.

## Files
- `app.py` — API and background download job
- `requirements.txt` — Python dependencies
- `Dockerfile` — container build, including ffmpeg

## Deploy on Render
1. Push these files to the root of the GitHub repository connected to Render.
2. Ensure the service uses Docker and deploy the latest commit.
3. In Render Environment, set:
   - `API_TOKEN`: a long random secret. Do not post it in Discord or share it publicly.
   - `PUBLIC_BASE_URL`: your Render service URL, without a trailing slash, e.g. `https://botghost-ytdlp-api.onrender.com`.
4. Open `/health`. The response should include `ok: true` and `yt_dlp_version`.

## API
### POST `/download`
Headers:
- `Authorization: Bearer YOUR_API_TOKEN`
- `Content-Type: application/json`

JSON body:
```json
{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}
```
Returns HTTP `202` with `job_id`, `status_url`, and the installed yt-dlp version.

### GET `/status/JOB_ID`
Returns `processing`, `done`, or `error`. When `done`, response contains `download_url`.

### GET `/files/JOB_ID`
Downloads the completed file.

## Limits and caveats
- Maximum duration: 10 minutes.
- Maximum file size: 40 MB.
- Jobs and files are temporary; jobs are held in memory and files are stored under `/tmp`. A Render restart or instance sleep/replacement can lose them.
- A current yt-dlp version cannot guarantee every YouTube video will work. YouTube may change its player, restrict a video, or require access this API does not have. This API does not attempt to bypass sign-in, age, region, or other access restrictions.
- Render Free instances can sleep; do not treat this as a guaranteed 24/7 service.
