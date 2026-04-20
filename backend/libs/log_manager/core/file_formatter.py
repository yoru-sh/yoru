import logging


class FileFormatter(logging.Formatter):
    """Plain text formatter for log files"""

    def format(self, record):
        # Get extra from record if it exists
        extra = getattr(record, "extra", {}) if hasattr(record, "extra") else {}

        # Format without colors
        formatted_log = (
            f"[{self.formatTime(record, self.datefmt)}] "  # Timestamp
            f"{record.levelname} "  # Level
            f"Module: {record.name} "  # Module
            f"Message: {record.getMessage()}"  # Main message
        )

        # Add correlation ID if present
        if "correlation_id" in extra:
            formatted_log += f" Correlation ID: {extra['correlation_id']}"

        # Add any other extra fields
        for key, value in extra.items():
            if key != "correlation_id":
                formatted_log += f" {key.title()}: {value}"

        return formatted_log
