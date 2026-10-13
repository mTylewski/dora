"""Law firm settings, lawyers, case numbering and the letter template library."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Case, FirmSettings, Lawyer, LetterTemplate
from pipeline.letter import TEMPLATE, check_template, load_letter_config

DEFAULT_TEMPLATE_ID = 0
DEFAULT_TEMPLATE_NAME = "Wezwanie przedsądowe do zapłaty (szablon domyślny)"
LAWYER_TITLES = ("adwokat", "radca prawny", "aplikant adwokacki", "aplikant radcowski")


def get_settings(db: Session) -> FirmSettings:
    """Settings row; created on first use from config/letter.yaml defaults."""
    settings = db.get(FirmSettings, 1)
    if settings is None:
        cfg = load_letter_config()
        firm = cfg.get("firm", {})
        settings = FirmSettings(
            id=1,
            name=_clean(firm.get("name")),
            address=_clean(firm.get("address")),
            city=_clean(firm.get("city")),
            payment_deadline_days=int(cfg.get("payment_deadline_days", 14)),
            legal_basis=(cfg.get("legal_basis") or {}).get("text") or "",
            bank_account="",
            case_number_pattern="KAN/{rok}/{nr}",
        )
        db.add(settings)
        db.flush()
    return settings


def _clean(value: str | None) -> str:
    """Placeholders like "[NAZWA KANCELARII]" from the sample config count as empty."""
    value = (value or "").strip()
    return "" if value.startswith("[") and value.endswith("]") else value


def next_case_number(db: Session, pattern: str, today: dt.date | None = None) -> str:
    """Next number for the pattern, e.g. KAN/{rok}/{nr} -> KAN/2026/007 (numbering restarts every year)."""
    today = today or dt.date.today()
    pattern = pattern or "KAN/{rok}/{nr}"
    if "{nr}" not in pattern:
        pattern += "/{nr}"
    regex = re.compile(
        "^" + re.escape(pattern).replace(re.escape("{rok}"), str(today.year)).replace(re.escape("{nr}"), r"(\d+)")
        + "$"
    )
    used = [int(m.group(1)) for n in db.scalars(select(Case.case_number)) if n and (m := regex.match(n))]
    return pattern.replace("{rok}", str(today.year)).replace("{nr}", f"{max(used, default=0) + 1:03d}")


def active_lawyers(db: Session) -> list[Lawyer]:
    return list(db.scalars(select(Lawyer).where(Lawyer.active).order_by(Lawyer.full_name)))


def lawyer_for_user(db: Session, user_id: int) -> Lawyer | None:
    return db.scalar(select(Lawyer).where(Lawyer.user_id == user_id, Lawyer.active))


@dataclass(frozen=True)
class TemplateInfo:
    id: int
    name: str
    description: str
    path: Path
    builtin: bool


def list_templates(db: Session, data_dir: Path) -> list[TemplateInfo]:
    out = [TemplateInfo(DEFAULT_TEMPLATE_ID, DEFAULT_TEMPLATE_NAME,
                        "Szablon dostarczony z systemem — punkt wyjścia do przygotowania własnego.", TEMPLATE, True)]
    for t in db.scalars(select(LetterTemplate).where(LetterTemplate.active).order_by(LetterTemplate.name)):
        out.append(TemplateInfo(t.id, t.name, t.description, templates_dir(data_dir) / t.stored_name, False))
    return out


def get_template(db: Session, data_dir: Path, template_id: int) -> TemplateInfo:
    for t in list_templates(db, data_dir):
        if t.id == template_id:
            return t
    raise ValueError("nie ma takiego szablonu")


def templates_dir(data_dir: Path) -> Path:
    return data_dir / "templates"


def add_template(db: Session, data_dir: Path, name: str, description: str, content: bytes
                 ) -> tuple[LetterTemplate | None, list[str], list[str]]:
    """Validate and store a firm template. Returns (template, errors, warnings)."""
    if not name.strip():
        return None, ["Podaj nazwę rodzaju pisma."], []
    directory = templates_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.docx"
    path = directory / stored
    path.write_bytes(content)
    errors, warnings = check_template(path)
    if errors:
        path.unlink(missing_ok=True)
        return None, errors, warnings
    template = LetterTemplate(name=name.strip()[:255], description=description.strip()[:1000], stored_name=stored)
    db.add(template)
    db.flush()
    return template, [], warnings


def deactivate_template(db: Session, template_id: int) -> None:
    template = db.get(LetterTemplate, template_id)
    if template is not None:
        template.active = False
