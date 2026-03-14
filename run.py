import os
import logging
import socket
from app import create_app


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


_configure_logging()
app = create_app(os.environ.get("FLASK_ENV", "default"))


def _is_port_available(port: int) -> bool:
    """Return True when a TCP port can be bound locally."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _resolve_server_port() -> int:
    """Resolve a usable server port, falling back when needed."""
    logger = logging.getLogger(__name__)
    fallback_base_port = 5005
    max_fallback_steps = 20

    raw_port = os.environ.get("PORT", str(fallback_base_port))
    try:
        requested_port = int(raw_port)
    except ValueError:
        logger.warning(
            "Invalid PORT value '%s'. Falling back to default %d.",
            raw_port,
            fallback_base_port,
        )
        requested_port = fallback_base_port

    for port in range(requested_port, requested_port + max_fallback_steps + 1):
        if _is_port_available(port):
            if port != requested_port:
                logger.warning(
                    "Port %d is in use. Falling back to available port %d.",
                    requested_port,
                    port,
                )
            return port

    raise RuntimeError(
        f"No available port found in range {requested_port}-{requested_port + max_fallback_steps}."
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=_resolve_server_port(), debug=False)
