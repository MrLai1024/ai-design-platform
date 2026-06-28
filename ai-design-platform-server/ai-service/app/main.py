"""AI 服务入口 — 启动 gRPC 服务器，提供 AI 生成/代理服务。"""

import asyncio
import logging
import signal
import sys
from concurrent import futures
from pathlib import Path

# 从项目根目录（ai-service/）加载 .env 文件
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    import os as _os
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                # 去除引号
                _val = _val.strip().strip('"').strip("'")
                _os.environ.setdefault(_key.strip(), _val)
    logging.getLogger(__name__).info("Loaded .env from %s", _env_path)

# Windows：gRPC aio 需要 selector 事件循环。
# 在导入 grpc 之前创建并设置循环，以便其 Cython 层
# 获取正在运行的循环，而不是创建自己的策略循环。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

import grpc
from ai.v1.generation_pb2_grpc import add_GenerationServiceServicer_to_server

from app.services.generation.servicer import GenerationServicer

logger = logging.getLogger(__name__)


def serve() -> None:
    """启动 gRPC 服务器并阻塞直到关闭。"""
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

    # 注册服务
    add_GenerationServiceServicer_to_server(GenerationServicer(), server)

    listen_addr = "[::]:50051"
    server.add_insecure_port(listen_addr)

    async def _run() -> None:
        await server.start()
        logger.info("AI gRPC server listening on %s", listen_addr)

        # 优雅关闭
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows：信号处理器仅在主线程中有效
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
