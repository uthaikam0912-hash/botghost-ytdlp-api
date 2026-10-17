import os
import re
import time
import uuid
import threading
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_file, abort
import yt_dlp

app = Flask(__name__)

API_TOKEN = os.environ.get("API_TOKEN", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DOWNLOAD_DIR = Path("/tmp/botghost-downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Demo storage: jobs are kept in memory and disappear when the service restarts.
jobs = {}
jobs_lock = threading.Lock()
MAX_BYTES = 40 * 1024 * 1024
MAX_DURATION_SECONDS = 600
JOB_TTL_SECONDS = 15 * 60


def allowed_video_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https"):
            return False
        return host in {
            "youtube.com", "www.youtube.com", "m.youtube.com",
            "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"
        }
    except Exception:
        return False


def cleanup_old():
    now = time.time()
    with jobs_lock:
        expired = [job_id for job_id, job in jobs.items()
                   if now - job["created_at"] > JOB_TTL_SECONDS]
        for job_id in expired:
            job = jobs.pop(job_id, None)
            if job and job.get("path"):
                try:
                    Path(job["path"]).unlink(missing_ok=True)
                except Exception:
                    pass


def do_download(job_id, url):
    output_template = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")
    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "format": "best[ext=mp4][filesize<40000000]/best[filesize<40000000]/best[ext=mp4]/best",
        "max_filesize": MAX_BYTES,
        "socket_timeout": 15,
        "retries": 1,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration > {MAX_DURATION_SECONDS}"
        ),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
            # Some formats may use a different extension after post-processing.
            if not path.exists():
                candidates = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
                if candidates:
                    path = candidates[0]
            if not path.exists() or path.stat().st_size > MAX_BYTES:
                raise RuntimeError("ไฟล์มีขนาดใหญ่เกินขีดจำกัด หรือไม่พบไฟล์")
            with jobs_lock:
                jobs[job_id].update({
                    "status": "done",
                    "path": str(path),
                    "title": str(info.get("title", "video"))[:120],
                    "download_url": f"{PUBLIC_BASE_URL}/files/{job_id}"
                })
    except Exception as exc:
        # Keep user-facing errors generic; detailed error text may contain internals.
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id].update({
                    "status": "error",
                    "message": "ดาวน์โหลดไม่สำเร็จ อาจเป็น URL ที่ไม่รองรับ ไฟล์ใหญ่เกินไป หรือวิดีโอไม่พร้อมใช้งาน"
                })


@app.get("/")
def home():
    return jsonify({
        "service": "BotGhost video API",
        "status": "online",
        "note": "Use /health to check service status."
    })


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/download")
def create_download():
    cleanup_old()
    if not API_TOKEN or request.headers.get("Authorization") != f"Bearer {API_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()
    if not allowed_video_url(url):
        return jsonify({"error": "รองรับเฉพาะลิงก์ YouTube ที่ถูกต้อง"}), 400

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "created_at": time.time(),
            "path": None,
            "title": None,
            "download_url": None,
        }

    thread = threading.Thread(target=do_download, args=(job_id, url), daemon=True)
    thread.start()
    return jsonify({
        "ok": True,
        "job_id": job_id,
        "status": "processing",
        "status_url": f"{PUBLIC_BASE_URL}/status/{job_id}"
    }), 202


@app.get("/status/<job_id>")
def status(job_id):
    cleanup_old()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "ไม่พบงาน หรือหมดอายุแล้ว"}), 404
        response = {"job_id": job_id, "status": job["status"]}
        if job["status"] == "done":
            response.update({
                "title": job["title"],
                "download_url": job["download_url"],
                "expires_in_seconds": JOB_TTL_SECONDS
            })
        elif job["status"] == "error":
            response["message"] = job["message"]
    return jsonify(response)


@app.get("/files/<job_id>")
def get_file(job_id):
    cleanup_old()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.get("status") != "done" or not job.get("path"):
            abort(404)
        path = Path(job["path"])
        title = job.get("title", "video")
    if not path.exists():
        abort(404)
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._")[:80] or "video"
    return send_file(path, as_attachment=True, download_name=f"{safe_title}{path.suffix}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
