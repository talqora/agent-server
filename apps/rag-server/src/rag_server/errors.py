"""统一错误处理:与 Node 版错误体形状对齐({code?, message}),并保持 401 语义。

- 业务异常:ApiError(code, message, status)
- 鉴权失败:401 {code: "UNAUTHORIZED", message}
- 未找到:404 {message}
- 参数校验失败:400/422(形状与 Node ValidationPipe 不完全一致,但前端不解析错误体)
"""

from __future__ import annotations

import logging
from typing import Any

from agent_core.auth import UnauthorizedError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("rag_server.errors")


class ApiError(Exception):
    """业务异常:显式 code + 状态码。"""

    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code

    def body(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.code:
            payload["code"] = self.code
        payload["message"] = self.message
        return payload


class NotFoundError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(404, message)


class BadRequestError(ApiError):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(400, message, code)


class ConflictError(ApiError):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(409, message, code)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(UnauthorizedError)
    async def _unauthorized(_: Request, exc: UnauthorizedError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"code": "UNAUTHORIZED", "message": str(exc) or "未授权"},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": "VALIDATION_ERROR", "message": "参数校验失败", "detail": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=500, content={"code": "INTERNAL", "message": "服务器内部错误"}
        )
