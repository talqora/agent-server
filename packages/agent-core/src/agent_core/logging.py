"""统一日志初始化:带服务名,便于单机多服务排障。"""

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def setup_logging(service: str, level: str = "INFO") -> None:
    """初始化根 logger。service 形如 'rag-http' / 'rag-worker'(进日志名,便于过滤)。"""
    logging.basicConfig(
        level=level.upper(),
        format=_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # 降噪:uvicorn 访问日志保留,第三方库压到 WARNING
    for noisy in ("pymilvus", "openai", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger(service).info("logging initialized (level=%s)", level.upper())
