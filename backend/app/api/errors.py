from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.domain.models import WorkflowError
from app.domain.errors import AppError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"error": exc.error.model_dump()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Do not echo file contents or arbitrary request values in validation errors.
        return JSONResponse(status_code=422, content={"error": WorkflowError(
            code="VALIDATION_ERROR", message="请求参数不正确，请检查分析需求、数据集引用、文件解析选项或版本。"
        ).model_dump()})

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": WorkflowError(
            code="HTTP_ERROR", message=str(exc.detail)
        ).model_dump()})

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        import logging
        logging.getLogger(__name__).exception("Unexpected API error", exc_info=exc)
        return JSONResponse(status_code=500, content={"error": WorkflowError(
            code="INTERNAL_ERROR", message="服务暂时无法完成请求，请稍后重试。"
        ).model_dump()})
