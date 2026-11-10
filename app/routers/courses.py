import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import authorize_role
from app.models import Category, Course, CourseModule, User
from app.schemas import (
    ApiResponse, CourseCreateIn, CourseDetailOut, CourseOut, CourseUpdateIn,
    ModuleOut, ok,
)

router = APIRouter(prefix="/courses", tags=["Courses"])


@router.get("", response_model=ApiResponse[list[CourseOut]])
def list_courses(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Course).where(Course.is_published.is_(True))
    if q:
        stmt = stmt.where(Course.title.ilike(f"%{q}%"))
    if category_id:
        stmt = stmt.where(Course.category_id == category_id)
    stmt = stmt.order_by(Course.created_at.desc()).limit(limit).offset(offset)
    return ok(db.scalars(stmt).all())


@router.get("/{course_id}", response_model=ApiResponse[CourseDetailOut])
def get_course(course_id: uuid.UUID, db: Session = Depends(get_db)):
    course = db.scalar(
        select(Course)
        .where(Course.id == course_id, Course.is_published.is_(True))
        .options(selectinload(Course.modules))
    )
    if course is None:
        raise HTTPException(404, "Kursus tidak ditemukan")
    return ok(course)


@router.get("/{course_id}/modules", response_model=ApiResponse[list[ModuleOut]])
def list_modules(course_id: uuid.UUID, db: Session = Depends(get_db)):
    # Kursus harus ada dan published (sama seperti GET /courses/{id})
    course = db.scalar(
        select(Course).where(Course.id == course_id, Course.is_published.is_(True))
    )
    if course is None:
        raise HTTPException(404, "Kursus tidak ditemukan")
    modules = db.scalars(
        select(CourseModule)
        .where(CourseModule.course_id == course.id)
        .order_by(CourseModule.position)
    ).all()
    return ok(modules)


@router.post("", status_code=201, response_model=ApiResponse[CourseOut])
def create_course(
    body: CourseCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("instructor", "admin")),
):
    if db.get(Category, body.category_id) is None:
        raise HTTPException(404, "Kategori tidak ditemukan")
    course = Course(**body.model_dump(), instructor_id=user.id)
    db.add(course)
    db.commit()
    return ok(course, "Kursus berhasil dibuat")


@router.patch("/{course_id}", response_model=ApiResponse[CourseOut])
def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("instructor", "admin")),
):
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Kursus tidak ditemukan")
    # Instructor hanya boleh mengubah kursus miliknya; admin boleh semua.
    # 403 (bukan 404): kursus ini publik, jadi keberadaannya memang bukan rahasia.
    if user.role != "admin" and course.instructor_id != user.id:
        raise HTTPException(403, "Anda hanya boleh mengubah kursus milik sendiri")

    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "category_id" in changes and db.get(Category, changes["category_id"]) is None:
        raise HTTPException(404, "Kategori tidak ditemukan")
    for field, value in changes.items():
        setattr(course, field, value)
    db.commit()
    return ok(course, "Kursus berhasil diubah")
