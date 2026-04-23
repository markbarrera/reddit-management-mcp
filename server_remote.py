"""Remote server with Bearer token auth for team deployment.

Wraps the FastMCP app with an ASGI middleware that:
  - Serves / and /health without auth
  - Requires Bearer tokens for /mcp when REDDIT_MCP_API_KEYS is set
  - Logs the authenticated user alongside each request so MCP tool calls
    can be attributed to team members

API key format (comma-separated):
    REDDIT_MCP_API_KEYS="alice:sk-xyz,bob:sk-abc,scheduler:sk-ops"

Anything after the colon is the secret key; the label before it is the
team member's name that shows up in feedback logs. An entry with no colon
is treated as a single key with the name "default".

DNS rebinding protection is disabled since deployments typically sit
behind a trusted proxy (Railway, Cloud Run, etc.) and handle their own auth.
"""

import os
import json
import logging
import uvicorn

from server import mcp
from profile import get_profile
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def _parse_api_keys() -> dict[str, str]:
    """Parse API keys from environment. Returns {token: user_name}."""
    raw = os.environ.get("REDDIT_MCP_API_KEYS", "")
    if not raw:
        logger.warning("No REDDIT_MCP_API_KEYS set — auth disabled (single-user mode)")
        return {}
    keys = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            name, key = entry.split(":", 1)
            keys[key.strip()] = name.strip()
        else:
            keys[entry] = "default"
    logger.info(f"Loaded {len(keys)} API key(s) for users: {sorted(set(keys.values()))}")
    return keys


API_KEYS = _parse_api_keys()

mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)
mcp_app = mcp.streamable_http_app()
_profile = get_profile()


async def _json_response(send, data, status=200):
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
    """ASGI app wrapping MCP with auth, multi-user attribution, and health."""
    if scope["type"] == "lifespan":
        await mcp_app(scope, receive, send)
        return

    if scope["type"] == "http":
        path = scope.get("path", "")

        if path == "/health":
            from db import get_stats
            stats = get_stats()
            await _json_response(send, {
                "status": "healthy",
                "service": _profile.server_name(),
                "brand": _profile.brand_name,
                "threads_in_db": stats.get("total_threads", 0),
                "classified": stats.get("classified", 0),
                "feedback_entries": stats.get("feedback_entries", 0),
            })
            return

        if path == "/":
            await _json_response(send, {
                "service": f"{_profile.brand_name} Reddit Intelligence MCP",
                "mcp_endpoint": "/mcp",
                "health": "/health",
            })
            return

        if API_KEYS:
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if not auth.startswith("Bearer "):
                await _json_response(send, {"error": "Missing or invalid Authorization header"}, 401)
                return
            token = auth[7:]
            if token not in API_KEYS:
                await _json_response(send, {"error": "Invalid API key"}, 403)
                return
            # Stash the authenticated user on the scope so handlers could
            # read it later via context. For now this is logging-only; the
            # reddit_log_feedback tool takes a user_name parameter directly
            # so the client can attribute edits explicitly.
            user = API_KEYS[token]
            scope["mcp_user"] = user
            logger.info(f"auth ok: user={user} path={path}")

    await mcp_app(scope, receive, send)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(
        f"Starting {_profile.brand_name} Reddit Intelligence MCP on port {port} "
        f"(profile: {_profile.source_path.name})"
    )
    uvicorn.run(app, host="0.0.0.0", port=port)
