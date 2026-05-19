"""Remote server with Bearer token auth for Railway deployment.

Uses a thin ASGI wrapper that delegates lifespan events to the
FastMCP app (preserving its task group lifecycle) while handling
health and root endpoints directly.

DNS rebinding protection is disabled via TransportSecuritySettings
since we are behind Railway's proxy and handle our own Bearer-token auth.
"""

import os
import json
import logging
import uvicorn

from server import mcp
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def _seed_grounding_docs():
    """Idempotently load grounding docs from grounding_docs/ on startup."""
    try:
        from seed_grounding_docs import main as seed_main
        seed_main()
    except Exception as e:
        logger.warning(f"Grounding doc seeding skipped: {e}")


_seed_grounding_docs()


def _parse_api_keys() -> dict[str, str]:
    """Parse API keys from environment variable."""
    raw = os.environ.get("REDDIT_MCP_API_KEYS", "")
    if not raw:
        logger.warning("No REDDIT_MCP_API_KEYS set -- auth disabled")
        return {}
    keys = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            name, key = entry.split(":", 1)
            keys[key.strip()] = name.strip()
        else:
            keys[entry] = "default"
    return keys


API_KEYS = _parse_api_keys()

# Disable DNS rebinding protection — we're behind Railway's proxy
# and handle our own Bearer token auth.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)
mcp_app = mcp.streamable_http_app()


async def _json_response(send, data, status=200):
    """Send a JSON response."""
    body = json.dumps(data).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def app(scope, receive, send):
    """ASGI app wrapping MCP with auth and health routes.

    Lifespan events are delegated to the MCP app so that
    FastMCP task group is properly initialized.
    """
    # Delegate lifespan to MCP app (critical for task group init)
    if scope["type"] == "lifespan":
        await mcp_app(scope, receive, send)
        return

    if scope["type"] == "http":
        path = scope.get("path", "")

        # Health check - no auth required
        if path == "/health":
            from db import get_stats
            stats = get_stats()
            await _json_response(send, {
                "status": "healthy",
                "service": "onramp-funds-reddit-intelligence",
                "threads_in_db": stats.get("total_threads", 0),
                "classified": stats.get("classified", 0),
            })
            return

        # Root info - no auth required
        if path == "/":
            await _json_response(send, {
                "service": "Onramp Funds Reddit Intelligence MCP",
                "mcp_endpoint": "/mcp",
                "health": "/health",
            })
            return

        # Auth check for MCP endpoints
        if API_KEYS:
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if not auth.startswith("Bearer "):
                await _json_response(
                    send,
                    {"error": "Missing or invalid Authorization header"},
                    401,
                )
                return
            token = auth[7:]
            if token not in API_KEYS:
                await _json_response(send, {"error": "Invalid API key"}, 403)
                return

    await mcp_app(scope, receive, send)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Onramp Funds Reddit Intelligence MCP on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
