import httpx


class NotificationSender:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def dispatch(self, run_id):
        item = self.store.notification(run_id)
        if item is None:
            raise ValueError("Approval is required before dispatch")
        if item["status"] != "pending":
            # Includes unknown delivery after a crash: do not automatically resend.
            if item["status"] == "sending":
                self.store.update_notification(run_id, "delivery_unknown", "interrupted_delivery")
            return
        if self.settings.notification_mode == "mock":
            self.store.update_notification(run_id, "mock_sent", "local_simulation_only", True)
            return
        payload = item["payload"]
        if (
            any(s.get("simulated") for s in payload["sources"].values())
            or not payload["allocation"].get("availability_verified")
            or not payload["sources"]["generation"].get("validated")
        ):
            self.store.update_notification(run_id, "blocked", "unverified_or_simulated_inputs")
            return
        if not (self.settings.notification_url or "").startswith("https://"):
            self.store.update_notification(run_id, "blocked", "https_webhook_required")
            return
        token = self.settings.notification_token
        if not token or not token.get_secret_value():
            self.store.update_notification(run_id, "blocked", "notification_token_required")
            return
        self.store.update_notification(run_id, "sending", increment=True)
        try:
            with httpx.Client(timeout=self.settings.http_timeout, follow_redirects=False) as client:
                response = client.post(
                    self.settings.notification_url,
                    json=payload,
                    headers={
                        "Authorization": "Bearer " + token.get_secret_value(),
                        "Idempotency-Key": run_id,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError:
            self.store.update_notification(
                run_id, "delivery_unknown", "manual_reconciliation_required"
            )
            return
        self.store.update_notification(run_id, "sent")
