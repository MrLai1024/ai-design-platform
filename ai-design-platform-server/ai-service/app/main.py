"""AI Service entry point — starts gRPC server for AI generation/agent services."""

import asyncio
import logging
import signal
import sys
from concurrent import futures

# Windows: gRPC aio requires selector event loop.
# Create and set a loop BEFORE importing grpc so its Cython layer
# picks up the running loop instead of creating its own policy loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

import grpc
from ai.v1.generation_pb2_grpc import add_GenerationServiceServicer_to_server

from app.services.generation.servicer import GenerationServicer

logger = logging.getLogger(__name__)


def serve() -> None:
    """Start the gRPC server and block until shutdown."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    server = grpc.aio.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ("grpc.max_concurrent_streams", 100),
            ("grpc.keepalive_time_ms", 30000),
        ],
    )

    # Register services
    add_GenerationServiceServicer_to_server(GenerationServicer(), server)

    listen_addr = "[::]:50051"
    server.add_insecure_port(listen_addr)

    async def _run() -> None:
        await server.start()
        logger.info("AI gRPC server listening on %s", listen_addr)

        # Graceful shutdown
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows: signal handlers only work in main thread
                signal.signal(sig, lambda *_: stop_event.set())

        await stop_event.wait()
        await server.stop(grace=5)
        logger.info("Server stopped")

    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    serve()
