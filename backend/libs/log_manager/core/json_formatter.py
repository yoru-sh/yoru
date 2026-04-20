import logging
import os
import sys
from typing import Optional


class JsonFormatter(logging.Formatter):
    """Console formatter that outputs human-readable logs with optional colors.

    Color behavior:
    - NO_COLOR present: disabled
    - LOG_COLOR=true/false/on/off: force accordingly
    - LOG_COLOR=auto (default): enabled only when the stream is a TTY
    """

    COLORS = {
        "DEBUG": "\033[94m",  # Blue
        "INFO": "\033[92m",  # Green
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",  # Red
        "CRITICAL": "\033[95m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def __init__(self, use_colors: Optional[bool] = None, datefmt: Optional[str] = None):
        super().__init__(fmt=None, datefmt=datefmt)

        if os.getenv("NO_COLOR") is not None:
            self.use_colors = False
        elif use_colors is not None:
            self.use_colors = bool(use_colors)
        else:
            env_value = (os.getenv("LOG_COLOR", "auto") or "auto").strip().lower()
            if env_value in {"1", "true", "yes", "on"}:
                self.use_colors = True
            elif env_value in {"0", "false", "no", "off"}:
                self.use_colors = False
            else:
                try:
                    self.use_colors = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
                except Exception:
                    self.use_colors = False

    def format(self, record):
        # Compute color tokens
        if self.use_colors:
            level_color = self.COLORS.get(record.levelname, self.RESET)
            bold = self.BOLD
            reset = self.RESET
        else:
            level_color = ""
            bold = ""
            reset = ""

        # Get extra from record if it exists
        extra = getattr(record, "extra", {}) if hasattr(record, "extra") else {}

        # Readable format with optional colors
        formatted_log = (
            f"{bold}[{self.formatTime(record, self.datefmt)}]{reset} "
            f"{level_color}{record.levelname}{reset} "
            f"{bold}Module:{reset} {record.name} "
            f"{bold}Message:{reset} {record.getMessage()} "
        )

        # Add correlation ID if present
        if "correlation_id" in extra:
            formatted_log += f"{bold}Correlation ID:{reset} {extra['correlation_id']} "

        # Add any other extra fields
        for key, value in extra.items():
            if key != "correlation_id":
                formatted_log += f"{bold}{key.title()}:{reset} {value} "

        return formatted_log
