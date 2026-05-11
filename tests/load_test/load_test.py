"""Locust load test — Agent Starter Pack convention.

Run against a local backend:
    make backend  # in another shell
    make load-test

Or against a Cloud Run URL:
    locust -f tests/load_test/load_test.py --host https://YOUR-RUN-URL \
        -u 20 -r 2 -t 5m --headless

When IAP is enabled in front of Cloud Run, set IAP_ID_TOKEN in the env so the
Locust user attaches `Authorization: Bearer <id-token>` per request.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

QUESTIONS = [
    "What is our customer churn rate over the last 90 days, broken down by region?",
    "Summarize the top 5 risk exposures in the analytics dataset.",
    "How does our exposure profile compare to the industry average reported by BIS in 2025?",
    "List the most-queried tables in the analytics dataset this quarter.",
]


class AnalystUser(HttpUser):
    wait_time = between(2, 6)

    def on_start(self) -> None:
        self.user_id = f"locust-{uuid.uuid4().hex[:8]}"
        self.session_id: str | None = None
        token = os.environ.get("IAP_ID_TOKEN")
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"

    @task(10)
    def invoke_coordinator(self) -> None:
        body = {
            "message": random.choice(QUESTIONS),
            "user_id": self.user_id,
            "session_id": self.session_id,
        }
        with self.client.post("/invoke", json=body, name="POST /invoke", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return
            data = r.json()
            self.session_id = data.get("session_id")
            if not data.get("final_text"):
                r.failure("empty final_text")

    @task(2)
    def fetch_identity(self) -> None:
        self.client.get("/.well-known/agent-identity", name="GET /.well-known/agent-identity")

    @task(1)
    def healthz(self) -> None:
        self.client.get("/healthz", name="GET /healthz")
