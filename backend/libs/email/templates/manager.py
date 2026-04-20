# Standard library
from pathlib import Path

# Third-party
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Local
from libs.email.exceptions import EmailTemplateError
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id


class TemplateManager:
    """
    Singleton manager for email templates using Jinja2.

    Provides template rendering with caching for performance.
    Follows singleton pattern for resource efficiency.
    """

    _instance: "TemplateManager | None" = None
    _initialized: bool = False

    def __new__(cls) -> "TemplateManager":
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        logger: LoggingController | None = None,
    ) -> None:
        """
        Initialize template manager (only once due to singleton).

        Args:
            logger: Optional logger instance
        """
        # Only initialize once
        if TemplateManager._initialized:
            return

        self.logger = logger or LoggingController(app_name="TemplateManager")

        # Get templates directory
        current_dir = Path(__file__).parent
        templates_dir = current_dir

        if not templates_dir.exists():
            raise EmailTemplateError(
                f"Templates directory not found: {templates_dir}"
            )

        # Initialize Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        TemplateManager._initialized = True

        self.logger.log_info(
            "TemplateManager initialized",
            {
                "component": "TemplateManager",
                "templates_dir": str(templates_dir),
            },
        )

    def render(
        self,
        template_name: str,
        context: dict[str, str] | None = None,
    ) -> str:
        """
        Render a template with the given context.

        Args:
            template_name: Name of template file (e.g., "invitation.html")
            context: Variables to pass to template

        Returns:
            Rendered HTML string

        Raises:
            EmailTemplateError: If template not found or rendering fails
        """
        correlation_id = get_correlation_id()
        log_context = {
            "operation": "render_template",
            "component": "TemplateManager",
            "correlation_id": correlation_id,
            "template_name": template_name,
        }

        if context is None:
            context = {}

        self.logger.log_info("Rendering email template", log_context)

        try:
            template = self.env.get_template(template_name)
            rendered = template.render(**context)

            self.logger.log_info(
                "Template rendered successfully",
                {**log_context, "rendered_length": len(rendered)},
            )

            return rendered

        except Exception as e:
            # BLOC-004: Log before re-raise
            self.logger.log_error(
                "Template rendering failed",
                {
                    **log_context,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "context_keys": list(context.keys()) if context else [],
                },
            )
            # STRONG-003: Chain exceptions
            raise EmailTemplateError(
                f"Failed to render template '{template_name}': {str(e)}",
                correlation_id,
            ) from e

    def render_string(
        self,
        template_string: str,
        context: dict[str, str] | None = None,
    ) -> str:
        """
        Render a template from a string.

        Useful for dynamic templates or testing.

        Args:
            template_string: Template content as string
            context: Variables to pass to template

        Returns:
            Rendered HTML string

        Raises:
            EmailTemplateError: If rendering fails
        """
        correlation_id = get_correlation_id()

        if context is None:
            context = {}

        try:
            template = self.env.from_string(template_string)
            return template.render(**context)

        except Exception as e:
            self.logger.log_error(
                "String template rendering failed",
                {
                    "component": "TemplateManager",
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
            )
            raise EmailTemplateError(
                f"Failed to render string template: {str(e)}",
                correlation_id,
            ) from e
