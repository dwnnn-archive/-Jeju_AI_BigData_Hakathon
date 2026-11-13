import time
from uuid import uuid4


def submit(client, body):
    response = client.post("/api/v1/analyses", json=body, headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 202, response.text
    return wait_result(client, response.json()["id"])


def wait_result(client, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/analyses/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.01)
    raise AssertionError("Worker did not finish within test deadline")
