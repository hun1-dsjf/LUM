"""Entry point: ``python -m pet_hospital_mcp`` or the ``pet-hospital-mcp``
console script. Runs the ASGI app with uvicorn, bound to a configurable
localhost-only host/port.
"""

from __future__ import annotations

import os

from .config import load_config
from .logging_config import configure_logging, get_logger


def main() -> None:
    configure_logging()
    cfg = load_config()
    log = get_logger("pet_hospital_mcp.main")
    log.info(
        "starting pet-hospital-mcp",
        extra={
            "mcp_host": cfg.mcp_host,
            "mcp_port": cfg.mcp_port,
            "mcp_endpoint": cfg.mcp_url,
            "backend_base_url": cfg.backend_base_url,
        },
    )
    # Import uvicorn lazily so the module import itself stays light.
    import uvicorn

    uvicorn.run(
        "pet_hospital_mcp.server:app",
        host=cfg.mcp_host,
        port=cfg.mcp_port,
        log_level=os.environ.get("MCP_LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
