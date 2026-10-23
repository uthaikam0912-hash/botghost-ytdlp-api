# ALLDL Discord Bot

## Files
- `bot.py`: Discord bot source
- `requirements.txt`: Python dependencies
- `Dockerfile`: Runtime image with Python and FFmpeg

## Required environment variable
- `DISCORD_TOKEN`: Discord bot token (never commit it to GitHub)

Optional:
- `OWNER_IDS`: comma-separated Discord user IDs allowed to use `/dl` in addition to the server owner
- `USER_COOLDOWN`: seconds between requests per user (default 30)
- `MAX_JOBS`: concurrent download jobs (default 2)
- `DL_TIMEOUT`: timeout per individual download in seconds (default 600)

This bot only accepts YouTube URLs. Only download content you own or are authorized to download and follow YouTube's terms and applicable law.
