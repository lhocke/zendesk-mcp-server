import asyncio


def main():
    from . import server
    asyncio.run(server.main())


__all__ = ["main"]
