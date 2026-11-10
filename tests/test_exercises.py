"""Tes untuk 6 latihan mandiri (halaman 14 modul).

Prasyarat: tabel sudah dibuat (dengan kolom invoices.expired_at) dan seed sudah dijalankan.
Jalankan  : pytest -v
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Enrollment, Invoice, Payment, User
from app.routers.payments import sign_body
from app.security import hash_password
from tests.helpers import auth, callback, client, login, register_student


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def seeded_course():
    return client.get("/courses", params={"q": "REST API dengan FastAPI"}).json()["data"][0]


@pytest.fixture(scope="module")
def instructor_token():
    return login("instructor@skillbridge.id", "Instruktur123!")


@pytest.fixture(scope="module")
def admin_token():
    return login("admin@skillbridge.id", "Admin123!")


@pytest.fixture(scope="module")
def other_instructor_token():
    """Instructor kedua (seed hanya punya satu), dibuat langsung di database."""
    email = f"inst2-{uuid.uuid4().hex[:6]}@skillbridge.id"
    with SessionLocal() as db:
        db.add(User(full_name="Instruktur Dua", email=email,
                    password_hash=hash_password("Instruktur123!"), role="instructor"))
        db.commit()
    return login(email, "Instruktur123!")


def new_course(token: str, category_id: str, price: str = "75000.00") -> dict:
    r = client.post(
        "/courses",
        json={"category_id": category_id, "title": f"Kursus {uuid.uuid4().hex[:6]}", "price": price},
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def enroll_and_pay(student_token: str, course_id: str, method: str = "qris"):
    """Enroll lalu buat payment. Mengembalikan (enrollment, invoice, payment)."""
    h = auth(student_token)
    r = client.post("/enrollments", json={"course_id": course_id}, headers=h)
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    r = client.post("/payments", json={"invoice_id": d["invoice"]["id"], "method": method}, headers=h)
    assert r.status_code == 201, r.text
    return d["enrollment"], d["invoice"], r.json()["data"]


def expire_invoice(invoice_id: str):
    with SessionLocal() as db:
        inv = db.get(Invoice, uuid.UUID(invoice_id))
        inv.expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()


# ---------- Latihan 1: GET /courses/{id}/modules ----------
def test_modules_are_listed_in_order(seeded_course):
    r = client.get(f"/courses/{seeded_course['id']}/modules")
    assert r.status_code == 200
    data = r.json()["data"]
    assert [m["position"] for m in data] == [1, 2, 3, 4]
    assert data[0]["title"] == "Pengenalan REST"


def test_modules_errors():
    assert client.get(f"/courses/{uuid.uuid4()}/modules").status_code == 404
    assert client.get("/courses/abc/modules").status_code == 422


# ---------- Latihan 2: GET /payments/{id} ----------
def test_get_payment_checks_ownership(instructor_token, admin_token, seeded_course):
    owner = register_student()
    _, _, pay = enroll_and_pay(owner["token"], new_course(instructor_token, seeded_course["category_id"])["id"])

    r = client.get(f"/payments/{pay['id']}", headers=auth(owner["token"]))
    assert r.status_code == 200
    assert r.json()["data"]["external_ref"] == pay["external_ref"]

    intruder = register_student("intruder")
    assert client.get(f"/payments/{pay['id']}", headers=auth(intruder["token"])).status_code == 404
    assert client.get(f"/payments/{uuid.uuid4()}", headers=auth(owner["token"])).status_code == 404
    assert client.get(f"/payments/{pay['id']}").status_code == 401
    assert client.get(f"/payments/{pay['id']}", headers=auth(admin_token)).status_code == 403
    assert client.get("/payments/abc", headers=auth(owner["token"])).status_code == 422


# ---------- Latihan 3: PATCH /courses/{id} ----------
def test_patch_course_ownership(instructor_token, other_instructor_token, admin_token, seeded_course):
    course = new_course(instructor_token, seeded_course["category_id"])
    url = f"/courses/{course['id']}"

    # pemilik: boleh, dan hanya field yang dikirim yang berubah
    r = client.patch(url, json={"title": "Judul Baru"}, headers=auth(instructor_token))
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Judul Baru"
    assert r.json()["data"]["price"] == course["price"]

    # instructor lain: ditolak
    r = client.patch(url, json={"title": "Dibajak"}, headers=auth(other_instructor_token))
    assert r.status_code == 403
    assert client.get(url).json()["data"]["title"] == "Judul Baru"

    # admin: boleh mengubah kursus siapa pun
    r = client.patch(url, json={"price": "99000.00"}, headers=auth(admin_token))
    assert r.status_code == 200 and r.json()["data"]["price"] == "99000.00"


def test_patch_course_other_errors(instructor_token, seeded_course):
    course = new_course(instructor_token, seeded_course["category_id"])
    url = f"/courses/{course['id']}"
    student = register_student()
    assert client.patch(url, json={"title": "Abc"}, headers=auth(student["token"])).status_code == 403
    assert client.patch(url, json={"title": "Abc"}).status_code == 401
    assert client.patch(url, json={}, headers=auth(instructor_token)).status_code == 422
    assert client.patch(url, json={"price": "-5"}, headers=auth(instructor_token)).status_code == 422
    r = client.patch(url, json={"category_id": str(uuid.uuid4())}, headers=auth(instructor_token))
    assert r.status_code == 404
    r = client.patch(f"/courses/{uuid.uuid4()}", json={"title": "Abc"}, headers=auth(instructor_token))
    assert r.status_code == 404


# ---------- Latihan 4: invoice expired_at ----------
def test_invoice_has_future_expiry(instructor_token, seeded_course):
    student = register_student()
    course = new_course(instructor_token, seeded_course["category_id"])
    _, invoice, _ = enroll_and_pay(student["token"], course["id"])
    expired_at = datetime.fromisoformat(invoice["expired_at"])
    assert expired_at > datetime.now(timezone.utc) + timedelta(hours=23)


def test_paid_callback_on_expired_invoice_is_rejected(instructor_token, seeded_course):
    student = register_student()
    course = new_course(instructor_token, seeded_course["category_id"])
    enrollment, invoice, pay = enroll_and_pay(student["token"], course["id"])
    expire_invoice(invoice["id"])

    r = callback({"external_ref": pay["external_ref"], "status": "paid", "amount": pay["amount"]})
    assert r.status_code == 409

    # tidak ada state yang berubah (rollback)
    with SessionLocal() as db:
        assert db.scalar(select(Payment.status).where(Payment.id == uuid.UUID(pay["id"]))) == "pending"
        assert db.scalar(select(Invoice.status).where(Invoice.id == uuid.UUID(invoice["id"]))) == "unpaid"
        assert db.scalar(select(Enrollment.status).where(Enrollment.id == uuid.UUID(enrollment["id"]))) == "pending_payment"


def test_cannot_create_payment_for_expired_invoice(instructor_token, seeded_course):
    student = register_student()
    course = new_course(instructor_token, seeded_course["category_id"])
    r = client.post("/enrollments", json={"course_id": course["id"]}, headers=auth(student["token"]))
    invoice_id = r.json()["data"]["invoice"]["id"]
    expire_invoice(invoice_id)
    r = client.post("/payments", json={"invoice_id": invoice_id, "method": "qris"}, headers=auth(student["token"]))
    assert r.status_code == 409


# ---------- Latihan 5: signature HMAC-SHA256 atas raw body ----------
def test_callback_signature(instructor_token, seeded_course):
    student = register_student()
    course = new_course(instructor_token, seeded_course["category_id"])
    _, _, pay = enroll_and_pay(student["token"], course["id"])
    payload = {"external_ref": pay["external_ref"], "status": "paid", "amount": pay["amount"]}

    # tanpa header / signature acak -> 401
    assert callback(payload, signature=None).status_code == 401
    assert callback(payload, signature="0" * 64).status_code == 401

    # signature sah untuk body A, tetapi body diganti B (mis. nominal dimanipulasi) -> 401
    sig_for_a = sign_body(json.dumps(payload).encode())
    tampered = {**payload, "amount": "1.00"}
    assert callback(tampered, signature=sig_for_a).status_code == 401

    # signature dihitung dari JSON yang diformat ulang (bukan raw body asli) -> 401
    reformatted_sig = sign_body(json.dumps(payload, indent=2).encode())
    assert callback(payload, signature=reformatted_sig).status_code == 401

    # signature benar -> 200, dan status payment benar-benar berubah
    r = callback(payload)
    assert r.status_code == 200 and r.json()["data"]["status"] == "paid"
    r = client.get(f"/payments/{pay['id']}", headers=auth(student["token"]))
    assert r.json()["data"]["status"] == "paid"
