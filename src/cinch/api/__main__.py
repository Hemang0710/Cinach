"""Console entrypoint: ``python -m cinch.api`` runs the ASGI server."""

from __future__ import annotations

import uvicorn

from cinch.core.config import get_settings


def main() -> None:
    """Run the FastAPI app with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "cinch.api.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; bind all interfaces intentionally
        port=8000,
        log_level=settings.log_level.lower(),
        reload=settings.environment == "local",
    )


if __name__ == "__main__":
    main()
