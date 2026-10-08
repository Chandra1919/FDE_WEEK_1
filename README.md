# Work Order Tracker API

A small FastAPI service for creating and tracking work orders. Data is kept in memory, so it resets whenever the server restarts. The service also provides an optional GroqCloud-powered endpoint that summarizes work-order descriptions.

## Features

- Create, list, retrieve, and update the status of work orders
- Pydantic request and response validation
- Consistent structured errors for invalid input, missing records, and LLM failures
- Groq API key loaded from `.env` (never committed)
- Interactive OpenAPI documentation

## Run locally

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Add your free [GroqCloud](https://console.groq.com/keys) API key to `.env`, then start the server:

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for Swagger UI.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/work-orders` | Create a work order |
| `GET` | `/work-orders` | List all work orders |
| `GET` | `/work-orders/{order_id}` | Get one work order |
| `PATCH` | `/work-orders/{order_id}/status` | Update its status |
| `POST` | `/summarize` | Summarize a description with Groq |

Valid statuses are `open`, `in_progress`, `completed`, and `cancelled`.

### Examples

Create a work order:

```bash
curl -X POST http://127.0.0.1:8000/work-orders \
  -H 'Content-Type: application/json' \
  -d '{"title":"Leaking pipe","description":"Pipe leaks under the kitchen sink in unit 3."}'
```

Update its status (replace the UUID):

```bash
curl -X PATCH http://127.0.0.1:8000/work-orders/WORK_ORDER_ID/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"in_progress"}'
```

Summarize a description:

```bash
curl -X POST http://127.0.0.1:8000/summarize \
  -H 'Content-Type: application/json' \
  -d '{"description":"The air conditioner on the second floor makes a grinding noise and no longer cools the offices."}'
```

Errors use a consistent envelope:

```json
{
  "error": {
    "code": "work_order_not_found",
    "message": "Work order '...' was not found."
  }
}
```

## Test

```bash
pytest
```

The LLM tests mock Groq, so tests do not require a real API key or network access.
