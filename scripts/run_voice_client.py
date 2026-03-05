"""Run the Gateway VoiceClient as a standalone process."""

import asyncio
import logging
import sys

from chintu_backend.clients import VoiceClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def main() -> int:
    client = VoiceClient()
    try:
        await client.start()
        while True:
            await asyncio.sleep(0.2)
    except KeyboardInterrupt:
        await client.stop()
        return 0
    except Exception as exc:
        logging.getLogger("voice_client").error("Fatal error: %s", exc, exc_info=True)
        try:
            await client.stop()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
