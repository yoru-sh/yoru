import json
import logging


class LokiJsonFormatter(logging.Formatter):
    """JSON formatter specifically for Loki to support structured logging"""

    def format(self, record):
        # Get the log message
        log_msg = record.getMessage()

        # Get extra from record if it exists
        extra = getattr(record, "extra", {}) if hasattr(record, "extra") else {}

        # Create base log data
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "module": record.name,
            "message": log_msg,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add all extra fields
        for key, value in extra.items():
            log_data[key] = value

        return json.dumps(log_data)
