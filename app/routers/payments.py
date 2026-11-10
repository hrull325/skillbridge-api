import hashlib
import hmac
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import authorize_role
from app.models import Enrollment, Invoice, Order, Payment, User
from app.schemas import (
    ApiResponse, PaymentCallbackIn, PaymentCreateIn, PaymentOut, ok,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


def _is_expired(invoice: Invoice) -> bool:
    return invoice.expired_at is not None and invoice.expired_at < datetime.now(timezone.utc)


def sign_body(raw_body: bytes) -> str:
    """HMAC-SHA256 (hex) atas raw body. Dipakai gateway untuk menandatangani, kita untuk memverifikasi."""
    return hmac.new(
        settings.payment_callback_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()


async def verify_callback_signature(
    request: Request,
    x_callback_signature: str | None = Header(default=None),
) -> None:
    # Harus RAW body (byte persis yang dikirim), bukan JSON hasil parse:
    # spasi/urutan key yang berbeda akan menghasilkan signature berbeda.
    raw_body = await request.body()
    expected = sign_body(raw_body)
    if not x_callback_signature or not hmac.compare_digest(
        x_callback_signature.strip().lower().encode(), expected.encode()
    ):
        raise HTTPException(401, "Signature callback tidak valid")


@router.post("", status_code=201, response_model=ApiResponse[PaymentOut])
def create_payment(
    body: PaymentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("student")),
):
    invoice = db.get(Invoice, body.invoice_id)
    order = db.get(Order, invoice.order_id) if invoice else None
    if invoice is None or order.student_id != user.id:
        raise HTTPException(404, "Invoice tidak ditemukan")
    if invoice.status != "unpaid":
        raise HTTPException(409, "Invoice sudah dibayar atau tidak aktif")
    if _is_expired(invoice):
        raise HTTPException(409, "Invoice sudah kedaluwarsa")

    pending = db.scalar(
        select(Payment).where(Payment.invoice_id == invoice.id, Payment.status == "pending")
    )
    if pending:
        raise HTTPException(409, "Masih ada pembayaran yang menunggu untuk invoice ini")

    payment = Payment(
        invoice_id=invoice.id,
        method=body.method,
        amount=invoice.amount,
        external_ref=f"SB-{uuid.uuid4().hex[:12].upper()}",
    )
    db.add(payment)
    db.commit()
    return ok(payment, "Pembayaran dibuat, menunggu konfirmasi gateway")


@router.get("/{payment_id}", response_model=ApiResponse[PaymentOut])
def get_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("student")),
):
    payment = db.get(Payment, payment_id)
    invoice = db.get(Invoice, payment.invoice_id) if payment else None
    order = db.get(Order, invoice.order_id) if invoice else None
    # 404 (bukan 403) agar tidak membocorkan keberadaan payment milik orang lain
    if order is None or order.student_id != user.id:
        raise HTTPException(404, "Pembayaran tidak ditemukan")
    return ok(payment)


@router.post(
    "/callback",
    response_model=ApiResponse[PaymentOut],
    dependencies=[Depends(verify_callback_signature)],
)
def payment_callback(
    body: PaymentCallbackIn,
    db: Session = Depends(get_db),
):
    # 1) Signature HMAC-SHA256 atas raw body sudah diverifikasi oleh dependency di atas:
    #    tanpa ini siapa pun bisa "melunasi" invoice sendiri.

    # 2) Kunci baris payment agar callback ganda tidak balapan
    payment = db.scalar(
        select(Payment).where(Payment.external_ref == body.external_ref).with_for_update()
    )
    if payment is None:
        raise HTTPException(404, "Pembayaran tidak ditemukan")

    # 3) Idempotent: callback yang sudah diproses tidak diproses ulang
    if payment.status != "pending":
        return ok(payment, "Callback sudah pernah diproses")

    # 4) Nominal harus cocok
    if body.amount != payment.amount:
        raise HTTPException(422, "Nominal callback tidak sesuai dengan tagihan")

    if body.status == "failed":
        payment.status = "failed"
        db.commit()
        return ok(payment, "Pembayaran ditandai gagal")

    # 5) PAID: invoice yang sudah kedaluwarsa tidak boleh dilunasi
    invoice = db.get(Invoice, payment.invoice_id)
    if _is_expired(invoice):
        raise HTTPException(409, "Invoice sudah kedaluwarsa, pembayaran ditolak")

    # 6) Update payment, invoice, order, enrollment secara konsisten (1 transaksi)
    now = datetime.now(timezone.utc)
    payment.status = "paid"
    payment.paid_at = now

    invoice.status = "paid"
    invoice.paid_at = now

    order = db.get(Order, invoice.order_id)
    order.status = "paid"

    enrollment = db.scalar(select(Enrollment).where(Enrollment.order_id == order.id))
    enrollment.status = "active"

    db.commit()  # semua berhasil, atau semua dibatalkan
    return ok(payment, "Pembayaran berhasil, enrollment aktif")
