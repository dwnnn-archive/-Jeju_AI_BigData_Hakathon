"""Measure HTTP status reads while a worker is deliberately blocked (local, not an SLA)."""

import json
import statistics
import tempfile
import time
from pathlib import Path
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def main():
    entered, release = Event(), Event()
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(database_path=Path(directory) / "benchmark.sqlite")
        with TestClient(create_app(settings)) as client:
            engine = client.app.state.service.engine
            original = engine.create

            def blocked(*args, **kwargs):
                entered.set()
                if not release.wait(30):
                    raise TimeoutError("Benchmark did not release worker")
                return original(*args, **kwargs)

            engine.create = blocked
            try:
                response = client.post(
                    "/api/v1/analyses",
                    json={"date": "2026-11-15", "mode": "demo"},
                    headers={"Idempotency-Key": str(uuid4())},
                )
                response.raise_for_status()
                run_id = response.json()["id"]
                assert entered.wait(5)
                for _ in range(100):
                    started = time.perf_counter()
                    result = client.get(f"/api/v1/analyses/{run_id}")
                    samples.append((time.perf_counter() - started) * 1000)
                    assert result.status_code == 200 and result.json()["status"] == "running"
            finally:
                release.set()
    print(
        json.dumps(
            {
                "measurement": "local TestClient HTTP GET while worker holds execution lock",
                "samples": len(samples),
                "median_ms": round(statistics.median(samples), 2),
                "p95_ms": round(sorted(samples)[94], 2),
                "max_ms": round(max(samples), 2),
                "network_included": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
