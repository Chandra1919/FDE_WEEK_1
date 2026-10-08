from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, work_orders


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store(monkeypatch: pytest.MonkeyPatch):
    work_orders.clear()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    yield
    work_orders.clear()


def test_work_order_lifecycle():
    created = client.post(
        "/work-orders",
        json={"title": "Leaking pipe", "description": "Pipe leaks under sink in unit 3."},
    )
    assert created.status_code == 201
    order = created.json()
    assert order["status"] == "open"

    assert client.get(f"/work-orders/{order['id']}").json() == order
    assert client.get("/work-orders").json() == [order]

    updated = client.patch(
        f"/work-orders/{order['id']}/status", json={"status": "in_progress"}
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"


def test_not_found_is_structured():
    response = client.get(f"/work-orders/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "work_order_not_found"


def test_validation_error_is_structured():
    response = client.post("/work-orders", json={"title": "", "description": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_summarize_requires_api_key():
    response = client.post("/summarize", json={"description": "Replace broken light."})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_not_configured"


def test_summarize_calls_groq(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    async def mock_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "Replace the broken light."}}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    response = client.post("/summarize", json={"description": "The light is broken."})
    assert response.status_code == 200
    assert response.json() == {"summary": "Replace the broken light."}
