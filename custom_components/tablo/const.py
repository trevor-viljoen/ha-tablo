"""Constants for the Tablo integration."""

from datetime import timedelta

DOMAIN = "tablo"
DEFAULT_PORT = 8887
SCAN_INTERVAL = timedelta(seconds=60)
MAX_SCHEDULED = 100

CONF_TRANSCODE_URL = "transcode_url"
CHANNEL_CACHE_TTL = timedelta(hours=6)
# How long a player may stay paused on live TV before the stream is stopped.
PAUSED_TIMEOUT = timedelta(minutes=10)
# Grace period after starting, while the player buffers/changes state.
START_GRACE = timedelta(seconds=45)
# Hard cap so a forgotten stream never holds a tuner forever.
MAX_SESSION_AGE = timedelta(hours=8)
