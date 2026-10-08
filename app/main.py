from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Annotated
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()


class WorkOrderStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkOrderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5_000)


class WorkOrderStatusUpdate(BaseModel):
    status: WorkOrderStatus


class WorkOrder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    status: WorkOrderStatus
    created_at: datetime
    updated_at: datetime


class SummarizeRequest(BaseModel):
    description: str = Field(min_length=1, max_length=5_000)


class SummarizeResponse(BaseModel):
    summary: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


work_orders: dict[UUID, WorkOrder] = {}
store_lock = Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Loading here makes local `.env` development work while keeping secrets out of source.
    load_dotenv()
    yield


app = FastAPI(
    title="Work Order Tracker API",
    version="1.0.0",
    description="Create, retrieve, list, and update work orders, with LLM summaries.",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        detail = exc.detail
    else:
        detail = {"code": "http_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": "The request data is invalid.",
                "details": exc.errors(),
            }
        },
    )


def not_found(order_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "work_order_not_found",
            "message": f"Work order '{order_id}' was not found.",
        },
    )


@app.post(
    "/work-orders",
    response_model=WorkOrder,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse}},
)
async def create_work_order(payload: WorkOrderCreate) -> WorkOrder:
    now = datetime.now(timezone.utc)
    order = WorkOrder(
        id=uuid4(),
        title=payload.title,
        description=payload.description,
        status=WorkOrderStatus.OPEN,
        created_at=now,
        updated_at=now,
    )
    with store_lock:
        work_orders[order.id] = order
    return order


@app.get("/work-orders", response_model=list[WorkOrder])
async def list_work_orders() -> list[WorkOrder]:
    with store_lock:
        return list(work_orders.values())


@app.get(
    "/work-orders/{order_id}",
    response_model=WorkOrder,
    responses={404: {"model": ErrorResponse}},
)
async def get_work_order(
    order_id: Annotated[UUID, Path(description="The work order UUID")],
) -> WorkOrder:
    with store_lock:
        order = work_orders.get(order_id)
    if order is None:
        raise not_found(order_id)
    return order


@app.patch(
    "/work-orders/{order_id}/status",
    response_model=WorkOrder,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def update_work_order_status(
    payload: WorkOrderStatusUpdate,
    order_id: Annotated[UUID, Path(description="The work order UUID")],
) -> WorkOrder:
    with store_lock:
        order = work_orders.get(order_id)
        if order is None:
            raise not_found(order_id)
        updated = order.model_copy(
            update={"status": payload.status, "updated_at": datetime.now(timezone.utc)}
        )
        work_orders[order_id] = updated
    return updated


@app.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def summarize_work_order(payload: SummarizeRequest) -> SummarizeResponse:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "llm_not_configured",
                "message": "GROQ_API_KEY is not configured.",
            },
        )

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.2,
                    "max_tokens": 150,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Summarize the work-order description in one or two concise "
                                "sentences. Preserve the key issue, location, and requested action."
                            ),
                        },
                        {"role": "user", "content": payload.description},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            summary = data["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "llm_provider_error",
                "message": "The summary provider could not complete the request.",
            },
        ) from exc

    if not summary:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "empty_llm_response",
                "message": "The summary provider returned an empty response.",
            },
        )
    return SummarizeResponse(summary=summary)
