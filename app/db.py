"""Database models (SQLAlchemy 2). Sensitive payloads are stored encrypted (app.crypto.Box)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="lawyer")  # lawyer | admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    title: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # uploaded -> preparing -> awaiting_approval -> analyzing -> ready | error
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    as_of: Mapped[dt.date] = mapped_column(Date)
    prepared_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    analysis_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    corrections_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    parties_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    letter_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    case_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    progress: Mapped[str | None] = mapped_column(String(200), nullable=True)
    progress_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    lawyer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    documents: Mapped[list[CaseDocument]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseDocument.doc_id"
    )


class CaseDocument(Base):
    __tablename__ = "case_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[str] = mapped_column(String(16))  # doc_1, doc_2, ...
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(64))
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    case: Mapped[Case] = relationship(back_populates="documents")


class FirmSettings(Base):
    """Law firm data used in letters; one row (id=1), edited by the admin."""

    __tablename__ = "firm_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    bank_account: Mapped[str] = mapped_column(String(64), default="")
    payment_deadline_days: Mapped[int] = mapped_column(Integer, default=14)
    case_number_pattern: Mapped[str] = mapped_column(String(64), default="KAN/{rok}/{nr}")
    legal_basis: Mapped[str] = mapped_column(String(2000), default="")


class Lawyer(Base):
    __tablename__ = "lawyers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(64), default="adwokat")  # adwokat | radca prawny | ...
    registry_no: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LetterTemplate(Base):
    """Firm template (.docx with {{placeholders}}); its name is the letter type shown in the wizard."""

    __tablename__ = "letter_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(1000), default="")
    stored_name: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccessLog(Base):
    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


def make_sessionmaker(database_url: str) -> sessionmaker:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _add_missing_columns(engine) -> None:
    """Additive migrations: new nullable columns on existing tables (no data changes)."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing and column.nullable:
                    ddl = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl}'))
