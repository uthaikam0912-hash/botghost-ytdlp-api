#!/usr/bin/env python3
"""ALLDL Discord bot: public /dl panel, private download results.

Environment variables:
  DISCORD_TOKEN   Required Discord bot token
  OWNER_IDS       Optional comma-separated user IDs allowed to run /dl
  USER_COOLDOWN   Per-user cooldown in seconds (default: 30)
  MAX_JOBS        Concurrent download jobs (default: 2)
  DL_TIMEOUT      Timeout per download in seconds (default: 600)
"""
import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import discord
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
MAX_JOBS = max(1, int(os.getenv("MAX_JOBS", "2")))
TIMEOUT = max(30, int(os.getenv("DL_TIMEOUT", "600")))
COOLDOWN = max(0, int(os.getenv("USER_COOLDOWN", "30")))
OWNER_IDS = {
    int(value)
    for value in os.getenv("OWNER_IDS", "").replace(" ", "").split(",")
    if value.isdigit()
}

MAX_BYTES = 10_000_000
RESOLUTIONS = ["144", "240", "360", "480", "720", "1080"]
AUDIO = "mp3"
YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be", "www.youtu.be",
}
download_semaphore = asyncio.Semaphore(MAX_JOBS)
last_use = {}


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in ("http", "https")
            and (parsed.hostname or "").lower() in YOUTUBE_HOSTS
        )
    except ValueError:
        return False


def build_ytdlp_command(url: str, kind: str, output_dir: Path):
    output_template = str(output_dir / "%(title).70s [%(id)s].%(ext)s")
    command = [
        "yt-dlp", "--no-config", "--newline", "--no-playlist",
        "--max-filesize", str(MAX_BYTES),
        "-o", output_template,
    ]

    if kind == AUDIO:
        command += [
            "-f", "bestaudio",
            "--extract-audio", "--audio-format", "mp3",
            "--audio-quality", "128K", "--add-metadata",
        ]
    else:
        fmt = (
            f"bv*[height<={kind}][vcodec^=avc1]+ba[acodec^=mp4a]"
            f"/bv*[height<={kind}]+ba/b[height<={kind}]/b"
        )
        command += ["-f", fmt, "--merge-output-format", "mp4"]

    command += ["--", url]
    return command


async def run_ytdlp(command):
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None, ""
    return process.returncode, output.decode("utf-8", errors="replace")


class QualitySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"วิดีโอ {resolution}p",
                value=resolution,
                default=(resolution == "360"),
            )
            for resolution in RESOLUTIONS
        ]
        options.append(
            discord.SelectOption(label="เสียง MP3 (128 kbps)", value=AUDIO, emoji="🎵")
        )
        super().__init__(
            placeholder="เลือกวิดีโอ/เสียง ได้สูงสุด 3 รายการ",
            min_values=1,
            max_values=3,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_kinds = list(self.values)
        await interaction.response.edit_message(
            content="เลือกรูปแบบเรียบร้อยแล้ว กด **เริ่มดาวน์โหลด** เมื่อพร้อม",
            view=self.view,
        )


class DownloadModal(discord.ui.Modal, title="ดาวน์โหลดจาก YouTube"):
    link = discord.ui.TextInput(
        label="ลิงก์ YouTube",
        placeholder="https://www.youtube.com/watch?v=...",
        max_length=300,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        url = self.link.value.strip()
        if not is_youtube_url(url):
            await interaction.response.send_message(
                "ลิงก์ไม่ถูกต้อง รองรับเฉพาะ youtube.com และ youtu.be",
                ephemeral=True,
            )
            return

        now = time.monotonic()
        remaining = COOLDOWN - (now - last_use.get(interaction.user.id, -1e9))
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ กรุณารออีก {int(remaining) + 1} วินาทีแล้วลองใหม่",
                ephemeral=True,
            )
            return

        last_use[interaction.user.id] = now
        view = QualityView(url, interaction.user.id)
        await interaction.response.send_message(
            "เลือกรูปแบบที่ต้องการดาวน์โหลด (ไฟล์แต่ละไฟล์ต้องไม่เกิน 10 MB)",
            view=view,
            ephemeral=True,
        )


class QualityView(discord.ui.View):
    def __init__(self, url: str, user_id: int):
        super().__init__(timeout=300)
        self.url = url
        self.user_id = user_id
        self.selected_kinds = ["360"]
        self.add_item(QualitySelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "เมนูนี้เป็นของผู้ใช้ที่เปิดฟอร์มเท่านั้น", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="เริ่มดาวน์โหลด", style=discord.ButtonStyle.success, emoji="📥")
    async def start_download(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass

        async with download_semaphore:
            with tempfile.TemporaryDirectory(prefix="alldl_") as temp_dir:
                root = Path(temp_dir)
                for kind in self.selected_kinds:
                    label = "MP3" if kind == AUDIO else f"{kind}p"
                    extension = ".mp3" if kind == AUDIO else ".mp4"
                    output_dir = root / kind
                    output_dir.mkdir(parents=True, exist_ok=True)
                    command = build_ytdlp_command(self.url, kind, output_dir)
                    code, log = await run_ytdlp(command)

                    if code is None:
                        await interaction.followup.send(
                            f"⏱️ {label}: เกินเวลาสูงสุด {TIMEOUT} วินาที",
                            ephemeral=True,
                        )
                        continue
                    if code != 0:
                        tail = log.strip()[-900:] or "ไม่มีรายละเอียดจาก yt-dlp"
                        await interaction.followup.send(
                            f"❌ {label}: ดาวน์โหลดไม่สำเร็จ\n```text\n{tail}\n```",
                            ephemeral=True,
                        )
                        continue

                    files = [
                        path for path in output_dir.iterdir()
                        if path.is_file() and path.suffix.lower() == extension
                    ]
                    if not files:
                        await interaction.followup.send(
                            f"❌ {label}: ไม่พบไฟล์ผลลัพธ์ที่คาดไว้",
                            ephemeral=True,
                        )
                        continue

                    file_path = max(files, key=lambda path: path.stat().st_size)
                    if file_path.stat().st_size > MAX_BYTES:
                        await interaction.followup.send(
                            f"📦 {label}: ไฟล์ใหญ่เกิน 10 MB ลองเลือกความละเอียดต่ำลง",
                            ephemeral=True,
                        )
                        continue

                    try:
                        await interaction.followup.send(
                            content=f"✅ {label} — `{file_path.name}`",
                            file=discord.File(file_path, filename=file_path.name),
                            ephemeral=True,
                        )
                    except discord.HTTPException:
                        await interaction.followup.send(
                            f"❌ {label}: Discord ไม่ยอมรับไฟล์ อาจเกินขีดจำกัดการอัปโหลด",
                            ephemeral=True,
                        )


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ยืนยัน",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="alldl:confirm",
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(DownloadModal())


class AllDLBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(PanelView())
        await self.tree.sync()

    async def on_ready(self):
        print(f"พร้อมใช้งานในชื่อ {self.user} (id: {self.user.id})")


client = AllDLBot()


@client.tree.command(
    name="dl",
    description="(เจ้าของเซิร์ฟเวอร์) สร้างแผงดาวน์โหลดให้ทุกคน",
)
@app_commands.guild_only()
async def dl(interaction: discord.Interaction):
    if (
        interaction.guild is None
        or (
            interaction.user.id != interaction.guild.owner_id
            and interaction.user.id not in OWNER_IDS
        )
    ):
        await interaction.response.send_message(
            "🚫 คำสั่งนี้ใช้ได้เฉพาะเจ้าของเซิร์ฟเวอร์หรือผู้ใช้ที่กำหนดไว้",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="📥 ดาวน์โหลดจาก YouTube",
        description=(
            "กดปุ่ม **ยืนยัน** เพื่อกรอกลิงก์ YouTube แล้วเลือกวิดีโอหรือเสียง MP3\n"
            "ข้อจำกัด: ไฟล์แต่ละไฟล์ต้องไม่เกิน **10 MB**\n"
            "ผลลัพธ์จะแสดงเฉพาะผู้ที่ขอดาวน์โหลดเท่านั้น"
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed, view=PanelView())


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("กรุณาตั้งค่า Environment Variable DISCORD_TOKEN ก่อนรัน")
    for program in ("yt-dlp", "ffmpeg"):
        if shutil.which(program) is None:
            raise SystemExit(f"ไม่พบโปรแกรม {program} กรุณาติดตั้งก่อน")
    client.run(TOKEN)
