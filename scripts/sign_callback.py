"""Menghitung header X-Callback-Signature (HMAC-SHA256 hex) untuk body callback.

Contoh:
    python -m scripts.sign_callback '{"external_ref":"SB-ABC123","status":"paid","amount":"150000.00"}'

PENTING: body yang dikirim ke server harus PERSIS sama (byte per byte) dengan teks
yang ditandatangani di sini, termasuk spasi. Itulah sebabnya yang ditandatangani
adalah raw body, bukan JSON yang sudah di-parse.
Secret dibaca dari PAYMENT_CALLBACK_SECRET di file .env.
"""
import hashlib
import hmac
import sys

from app.config import settings

if len(sys.argv) != 2:
    sys.exit(__doc__)

body = sys.argv[1].encode()
print(hmac.new(settings.payment_callback_secret.encode(), body, hashlib.sha256).hexdigest())
