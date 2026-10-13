"""Case lifecycle, independent of HTTP. Used by the web app and the job worker."""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.corrections import (
    CorrectionError,
    apply_corrections,
    correction_kind,
    parse_value,
    amount_in_quote,
    value_matches_quote,
)
from app.crypto import Box
from app import firm
from app.db import AccessLog, Case, CaseDocument, Lawyer, User, utcnow
from pipeline.anonymize import restore
from pipeline.calculate import FIELD_LABELS, calculate_from_extraction
from pipeline.classify import DocumentClass
from pipeline.clauses import ClauseFlag, ClausesResult
from pipeline.documents import Document
from pipeline.extract import ExtractionResult
from pipeline.letter import (
    PLACEHOLDERS,
    LetterDraft,
    LetterParties,
    prepare_draft,
    render_draft,
    template_placeholders,
)
from pipeline.llm import LLMClient, LLMError
from pipeline.pdf_text import OcrFn
from pipeline.run import CaseAnalysis, PreparedCase, analysis_to_dict, analyze_case, prepare_case
from pipeline.schema import Extraction
from pipeline.verify_quotes import Issue, QuoteIssue

log = logging.getLogger("claims.app")


class Queue:
    """Runs jobs inline (dev/tests). The RQ-backed queue lives in app.jobs."""

    def enqueue(self, job: str, case_id: str) -> None:
        from app import jobs

        getattr(jobs, job)(case_id)


class ThreadQueue(Queue):
    """Local single-user mode without Redis: jobs run in a background thread,
    so the browser gets the page back immediately and polls the case status."""

    def enqueue(self, job: str, case_id: str) -> None:
        import threading

        threading.Thread(target=super().enqueue, args=(job, case_id), daemon=True).start()


class Services:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker,
        llm_factory: Callable[[], LLMClient],
        queue: Any | None = None,
        ocr: OcrFn | None = None,
        detectors: list | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.box = Box(settings.mapping_key)
        self.llm_factory = llm_factory
        self.queue = queue or Queue()
        self.ocr = ocr
        self.detectors = detectors or []

    # --- paths ------------------------------------------------------------------

    def case_dir(self, case_id: str) -> Path:
        return self.settings.data_dir / "cases" / case_id

    def document_path(self, doc: CaseDocument) -> Path:
        return self.case_dir(doc.case_id) / doc.stored_name

    # --- audit ------------------------------------------------------------------

    def audit(self, db: Session, user_id: int | None, case_id: str | None, action: str, ip: str | None) -> None:
        db.add(AccessLog(user_id=user_id, case_id=case_id, action=action, ip=ip))

    # --- lifecycle --------------------------------------------------------------

    def create_case(self, user: User, title: str, files: list[tuple[str, bytes]], as_of: dt.date,
                    ip: str | None = None, case_number: str | None = None, lawyer_id: int | None = None) -> str:
        if not files:
            raise ValueError("brak plików")
        case_id = uuid.uuid4().hex
        directory = self.case_dir(case_id)
        directory.mkdir(parents=True, exist_ok=False)
        with self.sessions() as db:
            if not (case_number or "").strip():
                case_number = firm.next_case_number(db, firm.get_settings(db).case_number_pattern)
            if lawyer_id is None:
                own = firm.lawyer_for_user(db, user.id)
                lawyer_id = own.id if own else None
            case = Case(id=case_id, title=title.strip() or "Sprawa", created_by=user.id, as_of=as_of,
                        case_number=case_number.strip()[:64], lawyer_id=lawyer_id)
            for i, (filename, content) in enumerate(files, start=1):
                if not content.startswith(b"%PDF"):
                    shutil.rmtree(directory, ignore_errors=True)
                    raise ValueError(f"plik nie jest PDF: {filename}")
                stored = f"{uuid.uuid4().hex}.pdf"
                (directory / stored).write_bytes(content)
                case.documents.append(CaseDocument(doc_id=f"doc_{i}", filename=Path(filename).name[:255],
                                                   stored_name=stored))
            db.add(case)
            self.audit(db, user.id, case_id, "case_create", ip)
            db.commit()
        self._set_status(case_id, "preparing")
        self.queue.enqueue("prepare_job", case_id)
        return case_id

    def run_prepare(self, case_id: str) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is None:
                return
            paths = [self.document_path(d) for d in case.documents]
        try:
            self._progress(case_id, "Rozpoczynanie odczytu dokumentów", 2)
            prepared = prepare_case(case_id, paths, ocr=self.ocr, detectors=self.detectors,
                                    progress=lambda text, pct: self._progress(case_id, text, pct))
        except Exception:
            log.exception("case=%s step=prepare failed", case_id)
            self._set_status(case_id, "error", "prepare_failed")
            return
        payload = {
            "documents": [{"id": d.id, "filename": d.filename, "pages": d.pages, "ocr_pages": d.ocr_pages}
                          for d in prepared.anonymized],
            "mapping": prepared.mapping,
            "replacements": prepared.replacements,
            "persons": prepared.persons,
        }
        with self.sessions() as db:
            case = db.get(Case, case_id)
            case.prepared_enc = self.box.seal(payload)
            case.status = "awaiting_approval"
            db.commit()
        if not self.settings.require_anon_approval:
            self.approve(case_id, user_id=None)

    def approve(self, case_id: str, user_id: int | None, ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is None or case.status != "awaiting_approval":
                raise ValueError("sprawa nie oczekuje na zatwierdzenie")
            case.status = "analyzing"
            self.audit(db, user_id, case_id, "anonymization_approved", ip)
            db.commit()
        self.queue.enqueue("analyze_job", case_id)

    def _prepared(self, case: Case) -> PreparedCase:
        data = self.box.open(case.prepared_enc)
        docs = [Document(d["id"], d["filename"], d["pages"], None, d["ocr_pages"]) for d in data["documents"]]
        return PreparedCase(case.id, docs, docs, data["mapping"], data["replacements"], data.get("persons", []))

    def run_analyze(self, case_id: str) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is None:
                return
            prepared = self._prepared(case)
            as_of = case.as_of
        try:
            analysis = analyze_case(self.llm_factory(), prepared, as_of,
                                    progress=lambda text, pct: self._progress(case_id, text, pct))
        except LLMError as exc:
            log.warning("case=%s step=analyze error=%s", case_id, exc.code)
            self._set_status(case_id, "error", exc.code)
            return
        except Exception:
            log.exception("case=%s step=analyze failed", case_id)
            self._set_status(case_id, "error", "internal_error")
            return
        stored = {
            "classification": [c.model_dump(mode="json") for c in analysis.classification],
            "extraction": analysis.extraction.extraction.model_dump(mode="json"),
            "issues": [_issue_dict(i) for i in analysis.extraction.issues],
            "clauses": [f.model_dump(mode="json") for f in analysis.clauses.flags],
            "clause_issues": [_issue_dict(i) for i in analysis.clauses.issues],
            "clauses_dropped": analysis.clauses.dropped_unknown_ids,
            "timings_ms": analysis.timings_ms,
        }
        with self.sessions() as db:
            case = db.get(Case, case_id)
            case.analysis_enc = self.box.seal(stored)
            types = {c.document_id: c.type for c in analysis.classification}
            for doc in case.documents:
                doc.doc_type = str(types.get(doc.doc_id, "other"))
            case.status = "ready"
            case.error_code = None
            db.commit()

    def retry(self, case_id: str, user_id: int, ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is None or case.status != "error":
                raise ValueError("sprawa nie jest w stanie błędu")
            job = "analyze_job" if case.prepared_enc else "prepare_job"
            case.status = "analyzing" if case.prepared_enc else "preparing"
            case.error_code = None
            self.audit(db, user_id, case_id, "retry", ip)
            db.commit()
        self.queue.enqueue(job, case_id)

    def _progress(self, case_id: str, text: str, pct: int) -> None:
        """Step description shown while a background job runs (technical text only, no document content)."""
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is not None:
                case.progress, case.progress_pct, case.progress_at = text[:200], max(0, min(100, pct)), utcnow()
                db.commit()

    def _set_status(self, case_id: str, status: str, error_code: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is not None:
                case.status = status
                case.error_code = error_code
                db.commit()

    # --- views ------------------------------------------------------------------

    def replacements(self, case: Case) -> list[dict[str, str]]:
        return self.box.open(case.prepared_enc)["replacements"] if case.prepared_enc else []

    def anonymized_preview(self, case: Case) -> list[dict[str, Any]]:
        if not case.prepared_enc:
            return []
        return self.box.open(case.prepared_enc)["documents"]

    def _analysis(self, case: Case) -> tuple[CaseAnalysis, Extraction, dict[str, str], dict[str, Any]]:
        stored = self.box.open(case.analysis_enc)
        corrections = self.box.open(case.corrections_enc) or {}
        extraction = apply_corrections(stored["extraction"], corrections)
        mapping = self.box.open(case.prepared_enc)["mapping"]
        clauses = ClausesResult([ClauseFlag.model_validate(f) for f in stored["clauses"]],
                                [_issue(i) for i in stored["clause_issues"]], stored["clauses_dropped"])
        analysis = CaseAnalysis(
            case_id=case.id,
            classification=[DocumentClass.model_validate(c) for c in stored["classification"]],
            extraction=ExtractionResult(extraction, [_issue(i) for i in stored["issues"]
                                                     if i["path"] not in corrections]),
            clauses=clauses,
            calculation=calculate_from_extraction(extraction, case.as_of),
            timings_ms=stored["timings_ms"],
        )
        return analysis, extraction, mapping, corrections

    def case_view(self, case: Case) -> dict[str, Any]:
        analysis, _, mapping, corrections = self._analysis(case)
        data = analysis_to_dict(analysis, mapping)
        mismatched = []
        for f in data["fields"]:
            entry = corrections.get(f["path"])
            f["corrected"] = entry is not None
            f["manual"] = entry is not None and not entry.get("confirmed", False)
            f["mismatch"] = f["manual"] and value_matches_quote(f["path"], f["value"], f["quote"]) is False
            f["quote_amount"] = (
                amount_in_quote(f["quote"]) if f["path"] == "price_gross" and f["value"] is None else None
            )
            if f["mismatch"]:
                mismatched.append(FIELD_LABELS.get(f["path"], f["path"]))
        if mismatched:
            data["calculation"]["warnings"].insert(
                0, "Wartość wpisana ręcznie nie zgadza się z liczbą w cytacie z dokumentu: "
                + ", ".join(mismatched) + " — sprawdź, czy nie ma pomyłki (np. o rząd wielkości).")
        return data

    def set_as_of(self, case_id: str, as_of: dt.date, user_id: int, ip: str | None = None) -> None:
        """Change the calculation date (ongoing delays are counted up to this day)."""
        with self.sessions() as db:
            case = db.get(Case, case_id)
            case.as_of = as_of
            self.audit(db, user_id, case_id, f"as_of:{as_of.isoformat()}", ip)
            db.commit()

    def correct(self, case_id: str, path: str, raw: str, user_id: int, ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            stored = self.box.open(case.analysis_enc)
            corrections = self.box.open(case.corrections_enc) or {}
            value = parse_value(correction_kind(path), raw)
            entry = {"value": value, "by": user_id, "at": utcnow().isoformat()}
            candidate = {**corrections, path: entry}
            corrected = apply_corrections(stored["extraction"], candidate)  # validates, raises CorrectionError
            original = apply_corrections(stored["extraction"], {})
            # Saving the value read from the document unchanged counts as a confirmation.
            unchanged = dict(corrected.iter_fields())[path].value == dict(original.iter_fields())[path].value
            entry["confirmed"] = unchanged
            case.corrections_enc = self.box.seal(candidate)
            self.audit(db, user_id, case_id, f"{'confirm' if unchanged else 'correct'}:{path}", ip)
            db.commit()

    def revert(self, case_id: str, path: str, user_id: int, ip: str | None = None) -> None:
        """Drop the lawyer's correction: the field goes back to the value read from the document."""
        with self.sessions() as db:
            case = db.get(Case, case_id)
            corrections = self.box.open(case.corrections_enc) or {}
            if corrections.pop(path, None) is not None:
                case.corrections_enc = self.box.seal(corrections)
                self.audit(db, user_id, case_id, f"revert:{path}"[:64], ip)
                db.commit()

    def confirm(self, case_id: str, path: str, user_id: int, ip: str | None = None) -> None:
        """Mark a flagged field as checked, keeping its value."""
        with self.sessions() as db:
            case = db.get(Case, case_id)
            stored = self.box.open(case.analysis_enc)
            corrections = self.box.open(case.corrections_enc) or {}
            current = apply_corrections(stored["extraction"], corrections)
            field = dict(current.iter_fields())[path]
            value = field.value.model_dump(mode="json") if hasattr(field.value, "model_dump") else field.value
            if path.startswith("annex_deadlines"):
                value = value["date"] if value else None
            elif isinstance(value, list):
                value = [str(v) for v in value]
            elif value is not None and not isinstance(value, (bool, str)):
                value = str(value)
            candidate = {**corrections, path: {"value": value, "by": user_id, "at": utcnow().isoformat(),
                                               "confirmed": True}}
            apply_corrections(stored["extraction"], candidate)
            case.corrections_enc = self.box.seal(candidate)
            self.audit(db, user_id, case_id, f"confirm:{path}", ip)
            db.commit()

    def letter_parties(self, case: Case) -> LetterParties:
        stored = self.box.open(case.parties_enc)
        return LetterParties(**stored) if stored else LetterParties()

    # --- case metadata -------------------------------------------------------------------

    def update_case_meta(self, case_id: str, case_number: str, lawyer_id: int | None, user_id: int,
                         ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            case.case_number = case_number.strip()[:64] or case.case_number
            case.lawyer_id = lawyer_id
            self.audit(db, user_id, case_id, "case_meta", ip)
            db.commit()

    def persons(self, case: Case) -> list[dict[str, Any]]:
        """Persons found in the komparycja (name, role, address) - local data, never sent to the API."""
        if not case.prepared_enc:
            return []
        return self.box.open(case.prepared_enc).get("persons", [])

    # --- letter: wizard -> edit -> download -------------------------------------------------

    def letter_draft(self, case: Case) -> dict[str, Any] | None:
        """Stored draft with metadata, or None. Values are already de-anonymized (local only)."""
        return self.box.open(case.letter_enc)

    def letter_defaults(self, case: Case, user_id: int) -> dict[str, Any]:
        """Pre-filled wizard data: firm settings, the case's lawyer, data read from the documents."""
        _, extraction, _, _ = self._analysis(case)
        stored = self.box.open(case.parties_enc) or {}
        with self.sessions() as db:
            settings = firm.get_settings(db)
            lawyers = firm.active_lawyers(db)
            own = firm.lawyer_for_user(db, user_id)
            templates = firm.list_templates(db, self.settings.data_dir)
            db.commit()
        agreement_date = extraction.agreement_date.value
        return {
            "templates": templates,
            "template_id": stored.get("template_id", templates[-1].id if templates else 0),
            "lawyers": lawyers,
            "lawyer_id": stored.get("lawyer_id") or case.lawyer_id or (own.id if own else None),
            "case_number": case.case_number or "",
            "clients": stored.get("clients") or self._client_suggestions(case),
            "detected_persons": self.persons(case),
            "developer_name": stored.get("developer_name") or extraction.developer_name.value or "",
            "developer_address": stored.get("developer_address", ""),
            "agreement_date": stored.get("agreement_date")
            or (agreement_date.strftime("%d.%m.%Y") if agreement_date else ""),
            "agreement_deed": stored.get("agreement_deed") or extraction.agreement_reference.value or "",
            "bank_account": stored.get("bank_account") or settings.bank_account,
            "payment_deadline_days": stored.get("payment_deadline_days") or settings.payment_deadline_days,
            "capped": stored.get("capped", False),
            "firm_ready": bool(settings.name and settings.city),
        }

    def _client_suggestions(self, case: Case) -> list[dict[str, Any]]:
        """Buyers from the komparycja (pre-selected); without them, persons of unknown role (not selected)."""
        persons = self.persons(case)
        buyers = [p for p in persons if p.get("role") == "buyer"]
        chosen = buyers or [p for p in persons if not p.get("role")]
        return [{"name": p["name"], "address": p.get("address") or "", "checked": bool(buyers)} for p in chosen]

    def letter_status(self, case: Case) -> dict[str, Any]:
        """Draft plus checks against the current calculation (it may change after corrections)."""
        stored = self.letter_draft(case)
        if stored is None:
            return {"draft": None}
        draft = LetterDraft.from_dict(stored["draft"])
        analysis, *_ = self._analysis(case)
        result = analysis.calculation.result
        current = None
        if result is not None:
            current = result.total_capped_grosze if draft.capped else result.total_uncapped_grosze
        return {
            "draft": draft,
            "template_name": stored.get("template_name", ""),
            "prepared_at": stored["prepared_at"],
            "saved_at": stored.get("saved_at"),
            "stale": current != draft.total_grosze,
            "current_total_grosze": current,
            "missing": draft.missing_fields(),
        }

    def prepare_letter(self, case_id: str, form: dict[str, Any], user_id: int, ip: str | None = None) -> None:
        """Build the draft from the wizard data. `form` keys: template_id, lawyer_id, case_number, clients
        [{name, address}], developer_name, developer_address, agreement_date, agreement_deed, bank_account,
        payment_deadline_days, capped."""
        with self.sessions() as db:
            case = db.get(Case, case_id)
            analysis, extraction, mapping, _ = self._analysis(case)
            settings = firm.get_settings(db)
            template = firm.get_template(db, self.settings.data_dir, int(form["template_id"]))
            lawyer = db.get(Lawyer, form["lawyer_id"]) if form.get("lawyer_id") else None
            if form.get("case_number"):
                case.case_number = str(form["case_number"]).strip()[:64]
            case.parties_enc = self.box.seal({k: v for k, v in form.items()})
            db.commit()
            firm_data = (settings.name, settings.address, settings.city, settings.legal_basis)
        clients = [c for c in form.get("clients", []) if c.get("name", "").strip()]
        parties = LetterParties(
            client_name=" i ".join(c["name"].strip() for c in clients),
            clients=tuple((c["name"].strip(), c.get("address", "").strip()) for c in clients),
            developer_name=form.get("developer_name", ""),
            developer_address=form.get("developer_address", ""),
            agreement_date=form.get("agreement_date", ""),
            agreement_deed=form.get("agreement_deed", ""),
            bank_account=form.get("bank_account", ""),
            case_number=form.get("case_number", ""),
            lawyer_name=lawyer.full_name if lawyer else "",
            lawyer_title=lawyer.title if lawyer else "",
            lawyer_registry=lawyer.registry_no if lawyer else "",
            firm_name=firm_data[0], firm_address=firm_data[1], city=firm_data[2], legal_basis=firm_data[3],
            payment_deadline_days=int(form.get("payment_deadline_days") or 14),
        )
        with_justification = "justification" in template_placeholders(template.path)
        draft = prepare_draft(self.llm_factory(), case_id, extraction, analysis.calculation, parties,
                              capped=bool(form.get("capped")), letter_date=dt.date.today(),
                              with_justification=with_justification)
        # The model saw only anonymized facts; put personal data back locally for editing.
        draft.values = {k: restore(v, mapping) for k, v in draft.values.items()}
        now = utcnow().isoformat()
        with self.sessions() as db:
            case = db.get(Case, case_id)
            case.letter_enc = self.box.seal({
                "draft": draft.to_dict(), "prepared_at": now, "prepared_by": user_id,
                "template_id": template.id, "template_name": template.name,
            })
            self.audit(db, user_id, case_id, f"letter_prepare:{template.id}", ip)
            db.commit()

    def save_letter(self, case_id: str, edits: dict[str, str], user_id: int, ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            stored = self.letter_draft(case)
            if stored is None:
                raise ValueError("brak projektu pisma")
            values = stored["draft"]["values"]
            changed = sorted(k for k, v in edits.items() if k in PLACEHOLDERS and values.get(k) != v)
            for key in changed:
                values[key] = edits[key].replace("\r\n", "\n").strip()
            stored["saved_at"] = utcnow().isoformat()
            case.letter_enc = self.box.seal(stored)
            self.audit(db, user_id, case_id, ("letter_edit:" + (",".join(changed) or "-"))[:64], ip)
            db.commit()

    def render_letter_file(self, case_id: str, user_id: int, ip: str | None = None) -> tuple[Path, str]:
        """Rendered .docx and a download file name based on the template name and case number."""
        with self.sessions() as db:
            case = db.get(Case, case_id)
            stored = self.letter_draft(case)
            if stored is None:
                raise ValueError("brak projektu pisma")
            try:
                template = firm.get_template(db, self.settings.data_dir, int(stored.get("template_id", 0)))
            except ValueError:  # template removed since: fall back to the default one
                template = firm.get_template(db, self.settings.data_dir, firm.DEFAULT_TEMPLATE_ID)
            self.audit(db, user_id, case_id, "letter_download", ip)
            db.commit()
            number = case.case_number or ""
        out = self.case_dir(case_id) / "pismo.docx"
        path = render_draft(LetterDraft.from_dict(stored["draft"]), template.path, out)
        safe = "".join(ch if ch.isalnum() else "_" for ch in f"{template.name}_{number}").strip("_")
        return path, f"{safe[:80]}_PROJEKT.docx"

    def discard_letter(self, case_id: str, user_id: int, ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            case.letter_enc = None
            self.audit(db, user_id, case_id, "letter_discard", ip)
            db.commit()

    def delete_case(self, case_id: str, user_id: int | None, ip: str | None = None) -> None:
        with self.sessions() as db:
            case = db.get(Case, case_id)
            if case is not None:
                db.delete(case)
            self.audit(db, user_id, case_id, "case_delete", ip)
            db.commit()
        shutil.rmtree(self.case_dir(case_id), ignore_errors=True)

    def purge_expired(self, now: dt.datetime | None = None) -> int:
        cutoff = (now or utcnow()) - dt.timedelta(days=self.settings.retention_days)
        with self.sessions() as db:
            ids = list(db.scalars(select(Case.id).where(Case.created_at < cutoff)))
        for case_id in ids:
            self.delete_case(case_id, None)
        return len(ids)


def _issue_dict(issue: QuoteIssue) -> dict[str, Any]:
    return {"path": issue.path, "issue": issue.issue.value, "found_page": issue.found_page}


def _issue(data: dict[str, Any]) -> QuoteIssue:
    return QuoteIssue(data["path"], Issue(data["issue"]), data.get("found_page"))
