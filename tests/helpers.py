"""Helper bersama untuk tes: client, auth, dan callback bertanda tangan HMAC."""
import json
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.routers.payments import sign_body

client = TestClient(app)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(email: str, password: str) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def register_student(prefix: str = "siswa") -> dict:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@mail.com"
    r = client.post(
        "/auth/register",
        json={"full_name": "Siswa Uji", "email": email, "password": "Rahasia123"},
    )
    assert r.status_code == 201, r.text
    return {"email": email, "token": login(email, "Rahasia123")}


def callback(payload: dict, signature: str | None = "auto"):
    """Kirim callback gateway.

    signature="auto" -> tanda tangani raw body dengan benar
    signature=None   -> tanpa header signature
    signature="..."  -> pakai nilai itu apa adanya
    """
    raw = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Callback-Signature"] = sign_body(raw)
    elif signature is not None:
        headers["X-Callback-Signature"] = signature
    return client.post("/payments/callback", content=raw, headers=headers)
