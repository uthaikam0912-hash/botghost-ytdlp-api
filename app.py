import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, abort, jsonify, request, send_file

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

API_TOKEN = os.getenv("API_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL", "https://botghost-ytdlp-api.onrender.com"
).rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

DOWNLOAD_DIR = Path("/tmp/botghost-downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_BYTES = 40 * 1024 * 1024
MAX_DURATION_SECONDS = 600
JOB_TTL_SECONDS = 15 * 60

jobs = {}
jobs_lock = threading.Lock()

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def allowed_video_url(value):
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme in {"http", "https"} and host in ALLOWED_HOSTS
    except (TypeError, ValueError):
        return False


def remove_job_files(job_id):
    for file_path in DOWNLOAD_DIR.glob(f"{job_id}.*"):
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            app.logger.warning("Could not remove temporary file for job %s", job_id)


def cleanup_old_jobs():
    now = time.time()
    expired = []
    with jobs_lock:
        for job_id, job in list(jobs.items()):
            if (
                job.get("status") != "processing"
                and now - job.get("created_at", now) > JOB_TTL_SECONDS
            ):
                expired.append(jobs.pop(job_id, None))
    for job in expired:
        if job and job.get("id"):
            remove_job_files(job["id"])


def mark_job_error(job_id, public_message):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update({
                "status": "error",
                "path": None,
                "download_url": None,
                "message": public_message,
            })


def do_download(job_id, url):
    output_template = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")
    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "format": "best[ext=mp4][filesize<40000000]/best[filesize<40000000]/best[ext=mp4]/best",
        "max_filesize": MAX_BYTES,
        "socket_timeout": 25,
        "retries": 2,
        "fragment_retries": 2,
        "quiet": True,
        "no_warnings": False,
        "restrictfilenames": True,
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration > {MAX_DURATION_SECONDS}"
        ),
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
            if not path.is_file():
                candidates = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
                path = candidates[0] if candidates else path
            if not path.is_file():
                raise RuntimeError("Downloaded file was not found")
            if path.stat().st_size > MAX_BYTES:
                raise RuntimeError("Downloaded file exceeded the size limit")

            title = str(info.get("title") or "video")[:120]
            with jobs_lock:
                if job_id not in jobs:
                    path.unlink(missing_ok=True)
                    return
                jobs[job_id].update({
                    "status": "done",
                    "path": str(path),
                    "title": title,
                    "download_url": f"{PUBLIC_BASE_URL}/files/{job_id}",
                    "message": None,
                })
        app.logger.info("Download completed: job=%s yt_dlp=%s", job_id, yt_dlp.version.__version__)

    except yt_dlp.utils.DownloadError as exc:
        # Keep technical detail in private server logs; do not expose it to Discord users.
        app.logger.warning("yt-dlp download error for job %s: %s", job_id, str(exc))
        message = (
            "YouTube ไม่สามารถส่งข้อมูลวิดีโอให้ระบบได้ในขณะนี้ "
            "อาจเกิดจาก yt-dlp ยังไม่รองรับการเปลี่ยนแปลงของ YouTube "
            "หรือวิดีโอต้องมีสิทธิ์เข้าถึงเพิ่มเติม ลองใหม่ภายหลัง "
            "หรือใช้ไฟล์/วิธีดาวน์โหลดอย่างเป็นทางการที่คุณได้รับอนุญาต"
        )
        mark_job_error(job_id, message)
        remove_job_files(job_id)
    except Exception:
        app.logger.exception("Unexpected download failure for job %s", job_id)
        mark_job_error(job_id, "ดาวน์โหลดไม่สำเร็จ โปรดตรวจสอบ Render Logs")
        remove_job_files(job_id)


@app.get("/")
def home():
    return jsonify({
        "service": "BotGhost video API",
        "status": "online",
        "yt_dlp_version": yt_dlp.version.__version__,
        "health_url": f"{PUBLIC_BASE_URL}/health",
    })


@app.get("/health")
def health():
    return jsonify({"ok": True, "yt_dlp_version": yt_dlp.version.__version__}), 200


@app.post("/download")
def create_download():
    cleanup_old_jobs()
    if not API_TOKEN:
        app.logger.error("API_TOKEN environment variable is missing")
        return jsonify({"error": "Server is not configured"}), 503
    if request.headers.get("Authorization", "") != f"Bearer {API_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Body must be a JSON object containing url"}), 400
    url = str(data.get("url", "")).strip()
    if not allowed_video_url(url):
        return jsonify({"error": "ส่งลิงก์ YouTube ที่ถูกต้องเท่านั้น"}), 400

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "status": "processing",
            "created_at": time.time(),
            "path": None,
            "title": None,
            "download_url": None,
            "message": None,
        }

    thread = threading.Thread(target=do_download, args=(job_id, url), daemon=True)
    thread.start()
    return jsonify({
        "ok": True,
        "job_id": job_id,
        "status": "processing",
        "status_url": f"{PUBLIC_BASE_URL}/status/{job_id}",
        "yt_dlp_version": yt_dlp.version.__version__,
    }), 202


@app.get("/status/<job_id>")
def status(job_id):
    cleanup_old_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({
                "ok": False,
                "job_id": job_id,
                "status": "not_found",
                "message": "ไม่พบงาน งานหมดอายุ หรือเซิร์ฟเวอร์เริ่มทำงานใหม่",
            }), 404
        response = {"ok": True, "job_id": job_id, "status": job["status"]}
        if job["status"] == "done":
            response.update({
                "title": job["title"],
                "download_url": job["download_url"],
                "expires_in_seconds": max(
                    0, int(JOB_TTL_SECONDS - (time.time() - job["created_at"]))
                ),
            })
        elif job["status"] == "error":
            response["message"] = job["message"]
    return jsonify(response), 200


@app.get("/files/<job_id>")
def get_file(job_id):
    cleanup_old_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job["status"] != "done" or not job.get("path"):
            abort(404)
        path = Path(job["path"])
        title = job.get("title") or "video"
    if not path.is_file():
        abort(404)
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._")[:80] or "video"
    return send_file(path, as_attachment=True, download_name=f"{safe_title}{path.suffix}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
