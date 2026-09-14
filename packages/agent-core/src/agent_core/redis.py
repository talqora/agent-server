"""Redis 连接封装。

两类用途,连接纪律不同:
- 命令连接(单例):publish / ping / 缓存等;
- 订阅连接(duplicate):pub/sub 进入订阅态后**不能**再发普通命令,必须独立连接。
"""

from redis.asyncio import Redis


class RedisClient:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis | None = None

    async def connect(self) -> None:
        client: Redis = Redis.from_url(self._url, decode_responses=True)
        await client.ping()
        self._client = client

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("RedisClient 未 connect()")
        return self._client

    async def duplicate(self) -> Redis:
        """给 pub/sub 用的独立连接。"""
        return Redis.from_url(self._url, decode_responses=True)

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
