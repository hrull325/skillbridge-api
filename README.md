# SkillBridge API (FastAPI) — Project Praktikum

API backend e-learning: register/login, katalog kursus, enrollment, pembayaran
(dengan callback payment gateway), dan progress belajar. Mengikuti
*Panduan Implementasi API SkillBridge*, dengan stack FastAPI + PostgreSQL.

## Prasyarat
- Python 3.10 atau lebih baru (`python --version`)
- Docker Desktop (untuk PostgreSQL) **atau** PostgreSQL lokal
- Insomnia (https://insomnia.rest)

## Menjalankan (Windows / Mac / Linux)

```bash
# 1) Database
docker compose up -d

# 2) Virtual environment
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
# .venv\Scripts\Activate.ps1       # Windows PowerShell

# 3) Dependency + konfigurasi
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env

# 4) Tabel + seed + server
python -m app.create_tables
python -m app.seed
uvicorn app.main:app --reload
```

- Swagger UI : http://localhost:8000/docs
- OpenAPI    : http://localhost:8000/openapi.json

## Akun seed
| Role       | Email                     | Password       |
|------------|---------------------------|----------------|
| admin      | admin@skillbridge.id      | Admin123!      |
| instructor | instructor@skillbridge.id | Instruktur123! |

Student dibuat sendiri lewat `POST /auth/register`.

## Insomnia
Import `insomnia/SkillBridge.insomnia.json` (Application → Import).
Alternatif: Import → From URL → `http://localhost:8000/openapi.json`.
Nilai env (`token`, `course_id`, dst.) disalin manual dari response sebelumnya.
Callback pembayaran memakai **signature HMAC-SHA256 atas raw body** (header `X-Callback-Signature`),
bukan token statis. Hitung signature-nya dengan:
```bash
python -m scripts.sign_callback '{"external_ref":"SB-XXXX","status":"paid","amount":"150000.00"}'
```
Tempel hasilnya ke env `callback_signature`. Body di Insomnia harus persis sama dengan teks yang ditandatangani.

## Endpoint tambahan (latihan mandiri)
| Method | Endpoint | Akses | Fungsi |
|--------|----------|-------|--------|
| GET    | `/courses/{id}/modules` | publik | Modul terurut berdasarkan `position` |
| GET    | `/payments/{id}`        | student pemilik | Status pembayaran (404 jika bukan miliknya) |
| PATCH  | `/courses/{id}`         | instructor pemilik / admin | Ubah sebagian field kursus |

Invoice kini punya `expired_at` (default 24 jam, atur lewat `INVOICE_EXPIRE_HOURS`).
Callback `paid` untuk invoice kedaluwarsa dan pembuatan payment untuk invoice kedaluwarsa ditolak dengan 409.

> **Database lama?** Kolom `invoices.expired_at` baru. Reset database (lihat bawah) atau jalankan:
> `ALTER TABLE invoices ADD COLUMN expired_at TIMESTAMPTZ;`

## Uji otomatis (untuk instruktur / cek mandiri)
```bash
pip install -r requirements-dev.txt
pytest -v
```
Tes memerlukan database yang sudah di-seed.

## Reset database
```bash
docker compose down -v && docker compose up -d
python -m app.create_tables && python -m app.seed
```

## Struktur
```
app/
  config.py  database.py  models.py  schemas.py  security.py  deps.py
  create_tables.py  seed.py  main.py
  routers/  auth.py  courses.py  enrollments.py  payments.py
scripts/sign_callback.py
tests/helpers.py  test_flow.py  test_exercises.py
insomnia/SkillBridge.insomnia.json
```
