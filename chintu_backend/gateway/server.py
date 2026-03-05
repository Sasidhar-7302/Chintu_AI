"""Gateway server entrypoint (delegates to interfaces.gateway)."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from chintu_backend.core.command_handler import CommandHandler
from chintu_backend.core.config import get_config
from chintu_backend.interfaces.gateway.server import GatewayServer

logger = logging.getLogger("Gateway")


async def run_gateway(host: Optional[str] = None, port: Optional[int] = None) -> None:
    config = get_config()
    handler = CommandHandler()
    server = GatewayServer(
        command_handler=handler,
        host=host or config.gateway_host,
        port=port or config.gateway_port,
        auth_token=config.gateway_auth_token,
    )
    await server.start()
    # keep running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


def main() -> None:
    config = get_config()
    logger.info("Starting Gateway server on %s:%s", config.gateway_host, config.gateway_port)
    try:
        asyncio.run(run_gateway())
    except KeyboardInterrupt:
        logger.info("Gateway server stopped")


if __name__ == "__main__":
    main()
