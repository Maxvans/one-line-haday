"""Constants for One Line HaDay."""
DOMAIN = "one_line_haday"
STORAGE_KEY = "one_line_haday"
STORAGE_VERSION = 1

PANEL_URL = "one-line-haday"
PANEL_TITLE = "One Line HaDay"
PANEL_ICON = "mdi:calendar-text"

VISIBILITIES = {"household", "private", "shared"}
ROLES = {"owner", "co_editor", "viewer"}

ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_PHOTO_BYTES = 15 * 1024 * 1024  # 15 MB
