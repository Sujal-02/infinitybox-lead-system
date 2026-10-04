"""Delivery seam for the Send button.

TODAY: a placeholder. It delivers nothing and only reports that the message was recorded.
LATER: replace `deliver` with a real call (Gmail via MCP or API) once credentials are added and real sending is confirmed.
Keep the same shape: take the outbox record, return {"delivered": bool, "status": str}. Nothing else in the app needs to change."""


def deliver(record: dict) -> dict:
    return {"delivered": False, "status": "Recorded (placeholder). Not emailed: real sending is not connected yet."}
