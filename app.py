
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
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://botghost-ytdlp-api.onrender.com"
).rstrip("/")

DOWNLOAD_DIR = Path("/tmp/botghost-downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_BYTES = 40 * 1024 * 1024
MAX_DURATION_SECONDS = 600
JOB_TTL_SECONDS = 15 * 60

jobs = {}
jobs_lock = threading.Lock()


def allowed_video_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        return (
            parsed.scheme in ("http", "https")
            and host in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "youtu.be",
                "youtube-nocookie.com",
                "www.youtube-nocookie.com",
            }
        )
    except Exception:
        return False


def cleanup_old():
    now = time.time()

    with jobs_lock:
        expired = [
            job_id
            for job_id, job in jobs.items()
            if now - job["created_at"] > JOB_TTL_SECONDS
            and job["status"] != "processing"
        ]

        for job_id in expired:
            job = jobs.pop(job_id, None)

            if job and job.get("path"):
                try:
                    Path(job["path"]).unlink(missing_ok=True)
                except OSError:
                    app.logger.warning(
                        "Could not remove expired file for job %s",
                        job_id
                    )


def do_download(job_id, url):
    output_template = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")

    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "format": (
            "best[ext=mp4][filesize<40000000]"
            "/best[filesize<40000000]/best[ext=mp4]/best"
        ),
        "max_filesize": MAX_BYTES,
        "socket_timeout": 20,
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

            # ตรวจไฟล์จริง เผื่อนามสกุลเปลี่ยนหลังประมวลผล
            if not path.exists():
                candidates = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
                if candidates:
                    path = candidates[0]

            if not path.is_file():
                raise RuntimeError("Downloaded file not found")

            if path.stat().st_size > MAX_BYTES:
                raise RuntimeError("File exceeds size limit")

            title = str(info.get("title", "video"))[:120]

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

        app.logger.info("Download completed for job %s", job_id)

    except Exception:
        app.logger.exception("Download failed for job %s", job_id)

        with jobs_lock:
            if job_id in jobs:
                jobs[job_id].update({
                    "status": "error",
                    "path": None,
                    "download_url": None,
                    "message": (
                        "ดาวน์โหลดไม่สำเร็จ "
                        "โปรดตรวจสอบ Render Logs"
                    ),
                })

        # ลบไฟล์บางส่วนที่อาจเกิดจากการดาวน์โหลดไม่สำเร็จ
        for path in DOWNLOAD_DIR.glob(f"{job_id}.*"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                app.logger.warning("Could not remove partial file")


@app.get("/")
def home():
    return jsonify({
        "service": "BotGhost video API",
        "status": "online",
        "health_url": f"{PUBLIC_BASE_URL}/health",
    })


@app.get("/health")
def health():
    return jsonify({"ok": True}), 200


@app.post("/download")
def create_download():
    cleanup_old()

    if (
        not API_TOKEN
        or request.headers.get("Authorization") != f"Bearer {API_TOKEN}"
    ):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()

    if not allowed_video_url(url):
        return jsonify({
            "error": "รองรับเฉพาะลิงก์ YouTube ที่ถูกต้อง"
        }), 400

    job_id = uuid.uuid4().hex

    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "created_at": time.time(),
            "path": None,
            "title": None,
            "download_url": None,
            "message": None,
        }

    thread = threading.Thread(
        target=do_download,
        args=(job_id, url),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "status": "processing",
        "status_url": f"{PUBLIC_BASE_URL}/status/{job_id}",
    }), 202


@app.get("/status/<job_id>")
def status(job_id):
    cleanup_old()

    with jobs_lock:
        job = jobs.get(job_id)

        if not job:
            return jsonify({
                "ok": False,
                "job_id": job_id,
                "status": "not_found",
                "message": (
                    "ไม่พบงาน งานหมดอายุ หรือเซิร์ฟเวอร์เริ่มทำงานใหม่"
                ),
            }), 404

        response = {
            "ok": True,
            "job_id": job_id,
            "status": job["status"],
        }

        if job["status"] == "done":
            response.update({
                "title": job["title"],
                "download_url": job["download_url"],
                "expires_in_seconds": max(
                    0,
                    int(
                        JOB_TTL_SECONDS
                        - (time.time() - job["created_at"])
                    ),
                ),
            })

        elif job["status"] == "error":
            response["message"] = job["message"]

    return jsonify(response), 200


@app.get("/files/<job_id>")
def get_file(job_id):
    cleanup_old()

    with jobs_lock:
        job = jobs.get(job_id)

        if not job or job["status"] != "done" or not job.get("path"):
            abort(404)

        path = Path(job["path"])
        title = job.get("title", "video")

    if not path.is_file():
        abort(404)

    safe_title = (
        re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._")[:80]
        or "video"
    )

    return send_file(
        path,
        as_attachment=True,
        download_name=f"{safe_title}{path.suffix}",
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
    )
