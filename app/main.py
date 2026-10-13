"""Web application for lawyers (server-rendered, no external assets).

Run: uvicorn app.main:build --factory --host 0.0.0.0 --port 8000   (behind a TLS reverse proxy)
"""


import datetime as dt
import io
from pathlib import Path
from typing import Annotated

import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    Throttle,
    check_csrf,
    csrf_token,
    hash_password,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.corrections import EDITABLE, CorrectionError
from app import firm
from app.db import AccessLog, Case, Lawyer, User
from app.presenters import ISSUE_LABELS, display_value, edit_hint, edit_value
from app.services import Queue, Services
from calculator.money import format_pln
from pipeline.clauses import load_library
from pipeline.letter import PLACEHOLDERS, TABLE_PLACEHOLDER

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ROLE_LABELS = {"buyer": "nabywca", "seller": "sprzedający", "representative": "pełnomocnik / przedstawiciel",
               "notary": "notariusz", None: "osoba z dokumentu"}
SESSION_HOURS = 8

FIELD_LABELS = {
    "developer_name": "Deweloper",
    "agreement_reference": "Numer aktu umowy (Rep. A)",
    "agreement_date": "Data zawarcia umowy deweloperskiej",
    "price_gross": "Cena brutto",
    "handover_deadline": "Termin wydania lokalu",
    "transfer_deadline": "Termin umowy przenoszącej",
    "penalty_basis": "Sposób naliczania kary",
    "penalty_rate": "Stawka kary",
    "penalty_cap": "Limit kary",
    "penalty_events": "Kara za",
    "exclusive_penalty_clause": "Kara wyłączna (bez odszkodowania ponad karę)",
    "waiver_of_claims": "Zrzeczenie się roszczeń",
    "actual_handover_date": "Faktyczne wydanie lokalu",
    "actual_transfer_date": "Faktyczna umowa przenosząca",
}
STATUS_LABELS = {
    "uploaded": "Przesłano", "preparing": "Odczyt i anonimizacja", "awaiting_approval": "Do zatwierdzenia",
    "analyzing": "Analiza", "ready": "Gotowe", "error": "Błąd",
}
ERROR_LABELS = {
    "prepare_failed": "Nie udało się odczytać plików PDF.",
    "invalid_output": "Model zwrócił niepoprawne dane (po ponownej próbie).",
    "refusal": "Model odmówił przetworzenia dokumentów.",
    "api_error": "Błąd usługi modelu językowego.",
    "api_connection_error": "Brak połączenia z usługą modelu językowego.",
    "internal_error": "Błąd wewnętrzny.",
}


def create_app(services: Services) -> FastAPI:
    from app import jobs

    if isinstance(services.queue, Queue):
        jobs.use_services(services)  # in-process jobs share this instance

    app = FastAPI(title="Analiza roszczeń", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=services.settings.secret_key,
        session_cookie="claims_session",
        max_age=SESSION_HOURS * 3600,
        same_site="strict",
        https_only=services.settings.secure_cookies,
    )
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals.update(
        field_labels=FIELD_LABELS, status_labels=STATUS_LABELS, error_labels=ERROR_LABELS, pln=format_pln,
        issue_labels=ISSUE_LABELS, display_value=display_value, edit_value=edit_value, edit_hint=edit_hint,
    )
    throttle = Throttle()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def ip(request: Request) -> str | None:
        return request.client.host if request.client else None

    def render(request: Request, name: str, user: User | None = None, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {"user": user, "csrf": csrf_token(request), **ctx})

    def current_user(request: Request) -> User:
        user_id = request.session.get("user_id")
        if not user_id:
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        with services.sessions() as db:
            user = db.get(User, user_id)
        if user is None or not user.active:
            request.session.clear()
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        return user

    def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Brak uprawnień.")
        return user

    def load_case(case_id: str, user: User, request: Request, action: str) -> Case:
        with services.sessions() as db:
            case = db.get(Case, case_id)
            if case is None:
                raise HTTPException(status_code=404, detail="Nie znaleziono sprawy.")
            case.documents  # load relationship
            services.audit(db, user.id, case_id, action, ip(request))
            db.commit()
        return case

    UserDep = Annotated[User, Depends(current_user)]
    AdminDep = Annotated[User, Depends(admin_user)]
    Csrf = Annotated[str, Form()]

    # --- auth -------------------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    def login(request: Request, email: Annotated[str, Form()], password: Annotated[str, Form()], csrf: Csrf):
        check_csrf(request, csrf)
        key = f"{ip(request)}:{email.lower()}"
        if throttle.blocked(key):
            return render(request, "login.html", error="Zbyt wiele prób. Spróbuj ponownie za 15 minut.")
        with services.sessions() as db:
            user = db.scalar(select(User).where(User.email == email.lower().strip()))
        if user is None or not user.active or not verify_password(user.password_hash, password):
            throttle.fail(key)
            return render(request, "login.html", error="Nieprawidłowy e-mail lub hasło.")
        request.session.clear()
        request.session["pending_user"] = user.id
        return RedirectResponse("/login/totp", status_code=303)

    @app.get("/login/totp", response_class=HTMLResponse)
    def totp_form(request: Request):
        if not request.session.get("pending_user"):
            return RedirectResponse("/login", status_code=303)
        return render(request, "totp.html")

    @app.post("/login/totp")
    def totp(request: Request, code: Annotated[str, Form()], csrf: Csrf):
        check_csrf(request, csrf)
        pending = request.session.get("pending_user")
        if not pending:
            return RedirectResponse("/login", status_code=303)
        key = f"totp:{pending}"
        if throttle.blocked(key):
            request.session.clear()
            return render(request, "login.html", error="Zbyt wiele prób. Spróbuj ponownie za 15 minut.")
        with services.sessions() as db:
            user = db.get(User, pending)
            if user is None or not verify_totp(user.totp_secret, code):
                throttle.fail(key)
                return render(request, "totp.html", error="Nieprawidłowy kod.")
            services.audit(db, user.id, None, "login", ip(request))
            db.commit()
        throttle.reset(key)
        request.session.clear()
        request.session["user_id"] = user.id
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request, csrf: Csrf):
        check_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- cases ----------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def case_list(request: Request, user: UserDep):
        with services.sessions() as db:
            cases = list(db.scalars(select(Case).order_by(Case.created_at.desc()).limit(200)))
            lawyers = {lw.id: lw.full_name for lw in db.scalars(select(Lawyer))}
        return render(request, "cases.html", user, cases=cases, lawyers=lawyers,
                      retention=services.settings.retention_days)

    def new_case_page(request: Request, user: User, **ctx):
        with services.sessions() as db:
            settings = firm.get_settings(db)
            number = firm.next_case_number(db, settings.case_number_pattern)
            lawyers = firm.active_lawyers(db)
            own = firm.lawyer_for_user(db, user.id)
            db.commit()
        return render(request, "case_new.html", user, today=dt.date.today().isoformat(), case_number=number,
                      lawyers=lawyers, own_lawyer_id=own.id if own else None, **ctx)

    @app.get("/cases/new", response_class=HTMLResponse)
    def case_new_form(request: Request, user: UserDep):
        return new_case_page(request, user)

    @app.post("/cases")
    async def case_create(
        request: Request, user: UserDep, csrf: Csrf,
        title: Annotated[str, Form()], as_of: Annotated[str, Form()],
        files: Annotated[list[UploadFile], File()],
        case_number: Annotated[str, Form()] = "", lawyer_id: Annotated[str, Form()] = "",
    ):
        check_csrf(request, csrf)
        limit = services.settings.max_upload_mb * 1024 * 1024
        payload = []
        total = 0
        for f in files:
            content = await f.read()
            total += len(content)
            if total > limit:
                return new_case_page(request, user, error="Pliki są zbyt duże.")
            if content:
                payload.append((f.filename or "dokument.pdf", content))
        try:
            case_id = services.create_case(user, title, payload, dt.date.fromisoformat(as_of), ip(request),
                                           case_number=case_number, lawyer_id=int(lawyer_id) if lawyer_id else None)
        except ValueError as exc:
            return new_case_page(request, user, error=str(exc))
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.post("/cases/{case_id}/meta")
    def case_meta(request: Request, case_id: str, user: UserDep, csrf: Csrf,
                  case_number: Annotated[str, Form()] = "", lawyer_id: Annotated[str, Form()] = ""):
        check_csrf(request, csrf)
        services.update_case_meta(case_id, case_number, int(lawyer_id) if lawyer_id else None, user.id, ip(request))
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def case_detail(request: Request, case_id: str, user: UserDep):
        case = load_case(case_id, user, request, "case_view")
        with services.sessions() as db:
            lawyers = firm.active_lawyers(db)
        ctx: dict = {"case": case, "lawyers": lawyers}
        if case.status == "awaiting_approval":
            ctx["replacements"] = services.replacements(case)
            ctx["preview"] = services.anonymized_preview(case)
        if case.status == "ready":
            view = services.case_view(case)
            library = {p.id: p for p in load_library()}
            ctx.update(view=view, library=library, editable=EDITABLE,
                       error=request.query_params.get("error"))
        return render(request, "case.html", user, **ctx)

    @app.post("/cases/{case_id}/approve")
    def case_approve(request: Request, case_id: str, user: UserDep, csrf: Csrf):
        check_csrf(request, csrf)
        try:
            services.approve(case_id, user.id, ip(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.post("/cases/{case_id}/retry")
    def case_retry(request: Request, case_id: str, user: UserDep, csrf: Csrf):
        check_csrf(request, csrf)
        try:
            services.retry(case_id, user.id, ip(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.post("/cases/{case_id}/as-of")
    def case_as_of(request: Request, case_id: str, user: UserDep, csrf: Csrf, as_of: Annotated[str, Form()]):
        check_csrf(request, csrf)
        try:
            services.set_as_of(case_id, dt.date.fromisoformat(as_of), user.id, ip(request))
        except ValueError:
            return RedirectResponse(f"/cases/{case_id}?error=Nieprawidłowa data#calculation", status_code=303)
        return RedirectResponse(f"/cases/{case_id}#calculation", status_code=303)

    @app.post("/cases/{case_id}/fields")
    def case_correct(request: Request, case_id: str, user: UserDep, csrf: Csrf,
                     path: Annotated[str, Form()], value: Annotated[str, Form()] = "",
                     action: Annotated[str, Form()] = "correct"):
        check_csrf(request, csrf)
        try:
            if action == "confirm":
                services.confirm(case_id, path, user.id, ip(request))
            elif action == "revert":
                services.revert(case_id, path, user.id, ip(request))
            else:
                services.correct(case_id, path, value, user.id, ip(request))
        except CorrectionError as exc:
            return RedirectResponse(f"/cases/{case_id}?error={exc}#fields", status_code=303)
        return RedirectResponse(f"/cases/{case_id}#fields", status_code=303)

    @app.get("/cases/{case_id}/documents/{doc_id}")
    def case_document(request: Request, case_id: str, doc_id: str, user: UserDep):
        case = load_case(case_id, user, request, f"document_view:{doc_id}")
        doc = next((d for d in case.documents if d.doc_id == doc_id), None)
        if doc is None:
            raise HTTPException(status_code=404)
        return FileResponse(services.document_path(doc), media_type="application/pdf",
                            headers={"Content-Disposition": "inline"})

    @app.get("/cases/{case_id}/letter", response_class=HTMLResponse)
    def letter_page(request: Request, case_id: str, user: UserDep, new: int = 0):
        case = load_case(case_id, user, request, "letter_view")
        status = services.letter_status(case)
        if status["draft"] is not None and not new:
            return render(request, "letter_edit.html", user, case=case, status=status,
                          placeholders=PLACEHOLDERS, saved=request.query_params.get("saved"))
        return letter_wizard(request, user, case, has_draft=status["draft"] is not None)

    def letter_wizard(request: Request, user: User, case: Case, **ctx):
        return render(request, "letter.html", user, case=case, view=services.case_view(case),
                      d=services.letter_defaults(case, user.id), role_labels=ROLE_LABELS, **ctx)

    @app.post("/cases/{case_id}/letter/prepare")
    async def letter_prepare(request: Request, case_id: str, user: UserDep):
        form = await request.form()
        check_csrf(request, str(form.get("csrf") or ""))
        names = form.getlist("client_name")
        addresses = form.getlist("client_address")
        include = set(form.getlist("client_include"))
        clients = [{"name": str(n), "address": str(a)} for i, (n, a) in enumerate(zip(names, addresses))
                   if str(i) in include and str(n).strip()]
        data = {
            "template_id": int(form.get("template_id") or 0),
            "lawyer_id": int(form["lawyer_id"]) if form.get("lawyer_id") else None,
            "case_number": str(form.get("case_number") or ""),
            "clients": clients,
            "developer_name": str(form.get("developer_name") or ""),
            "developer_address": str(form.get("developer_address") or ""),
            "agreement_date": str(form.get("agreement_date") or ""),
            "agreement_deed": str(form.get("agreement_deed") or ""),
            "bank_account": str(form.get("bank_account") or ""),
            "payment_deadline_days": int(form.get("payment_deadline_days") or 14),
            "capped": form.get("capped") == "yes",
        }
        try:
            services.prepare_letter(case_id, data, user.id, ip(request))
        except Exception as exc:  # LLMError, ValueError
            code = getattr(exc, "code", None) or "letter_failed"
            case = load_case(case_id, user, request, "letter_failed")
            return letter_wizard(request, user, case, error=ERROR_LABELS.get(code, str(exc)))
        return RedirectResponse(f"/cases/{case_id}/letter", status_code=303)

    @app.post("/cases/{case_id}/letter/save")
    async def letter_save(request: Request, case_id: str, user: UserDep):
        form = await request.form()
        check_csrf(request, str(form.get("csrf") or ""))
        edits = {k: str(form[k]) for k in PLACEHOLDERS if k in form}
        try:
            services.save_letter(case_id, edits, user.id, ip(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if form.get("action") == "download":
            return RedirectResponse(f"/cases/{case_id}/letter/download", status_code=303)
        return RedirectResponse(f"/cases/{case_id}/letter?saved=1", status_code=303)

    @app.get("/cases/{case_id}/letter/download")
    def letter_download(request: Request, case_id: str, user: UserDep):
        load_case(case_id, user, request, "letter_view")
        try:
            path, filename = services.render_letter_file(case_id, user.id, ip(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.post("/cases/{case_id}/letter/discard")
    def letter_discard(request: Request, case_id: str, user: UserDep, csrf: Csrf):
        check_csrf(request, csrf)
        services.discard_letter(case_id, user.id, ip(request))
        return RedirectResponse(f"/cases/{case_id}/letter", status_code=303)

    # --- firm templates (admin) ------------------------------------------------------------

    def templates_page(request: Request, user: User, **ctx):
        with services.sessions() as db:
            templates = firm.list_templates(db, services.settings.data_dir)
        return render(request, "admin_templates.html", user, templates=templates, placeholders=PLACEHOLDERS,
                      table_placeholder=TABLE_PLACEHOLDER, **ctx)

    @app.get("/admin/templates", response_class=HTMLResponse)
    def admin_templates(request: Request, user: AdminDep):
        return templates_page(request, user)

    @app.post("/admin/templates")
    async def admin_template_upload(request: Request, user: AdminDep, csrf: Csrf,
                                    file: Annotated[UploadFile, File()], name: Annotated[str, Form()] = "",
                                    description: Annotated[str, Form()] = ""):
        check_csrf(request, csrf)
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            return templates_page(request, user, error="Plik jest zbyt duży (maks. 10 MB).")
        with services.sessions() as db:
            template, errors, warnings = firm.add_template(db, services.settings.data_dir, name, description, content)
            if template is not None:
                services.audit(db, user.id, None, f"template_upload:{template.id}", ip(request))
            db.commit()
        if errors:
            return templates_page(request, user, error=" ".join(errors), warnings=warnings)
        return templates_page(request, user, uploaded=name, warnings=warnings)

    @app.post("/admin/templates/{template_id}/deactivate")
    def admin_template_deactivate(request: Request, template_id: int, user: AdminDep, csrf: Csrf):
        check_csrf(request, csrf)
        with services.sessions() as db:
            firm.deactivate_template(db, template_id)
            services.audit(db, user.id, None, f"template_remove:{template_id}", ip(request))
            db.commit()
        return RedirectResponse("/admin/templates", status_code=303)

    @app.get("/admin/templates/{template_id}/download")
    def admin_template_download(template_id: int, user: AdminDep):
        with services.sessions() as db:
            try:
                template = firm.get_template(db, services.settings.data_dir, template_id)
            except ValueError as exc:
                raise HTTPException(status_code=404) from exc
        safe = "".join(ch if ch.isalnum() else "_" for ch in template.name)[:60]
        return FileResponse(template.path, filename=f"{safe}.docx", media_type=DOCX_MEDIA)

    @app.get("/admin/firm", response_class=HTMLResponse)
    def admin_firm(request: Request, user: AdminDep):
        return firm_page(request, user, saved=request.query_params.get("saved"))

    def firm_page(request: Request, user: User, **ctx):
        with services.sessions() as db:
            settings = firm.get_settings(db)
            lawyers = list(db.scalars(select(Lawyer).order_by(Lawyer.active.desc(), Lawyer.full_name)))
            users = list(db.scalars(select(User).order_by(User.email)))
            example = firm.next_case_number(db, settings.case_number_pattern)
            db.commit()
        return render(request, "admin_firm.html", user, settings=settings, lawyers=lawyers, users=users,
                      titles=firm.LAWYER_TITLES, example=example, **ctx)

    @app.post("/admin/firm")
    def admin_firm_save(request: Request, user: AdminDep, csrf: Csrf,
                        name: Annotated[str, Form()] = "", address: Annotated[str, Form()] = "",
                        city: Annotated[str, Form()] = "", bank_account: Annotated[str, Form()] = "",
                        payment_deadline_days: Annotated[int, Form()] = 14,
                        case_number_pattern: Annotated[str, Form()] = "KAN/{rok}/{nr}",
                        legal_basis: Annotated[str, Form()] = ""):
        check_csrf(request, csrf)
        with services.sessions() as db:
            settings = firm.get_settings(db)
            settings.name, settings.address, settings.city = name.strip(), address.strip(), city.strip()
            settings.bank_account = bank_account.strip()
            settings.payment_deadline_days = max(1, payment_deadline_days)
            settings.case_number_pattern = case_number_pattern.strip() or "KAN/{rok}/{nr}"
            settings.legal_basis = legal_basis.strip()
            services.audit(db, user.id, None, "firm_settings", ip(request))
            db.commit()
        return RedirectResponse("/admin/firm?saved=1", status_code=303)

    @app.post("/admin/firm/lawyers")
    def admin_lawyer_save(request: Request, user: AdminDep, csrf: Csrf,
                          full_name: Annotated[str, Form()], title: Annotated[str, Form()] = "adwokat",
                          registry_no: Annotated[str, Form()] = "", user_id: Annotated[str, Form()] = "",
                          lawyer_id: Annotated[str, Form()] = "", active: Annotated[str, Form()] = "yes"):
        check_csrf(request, csrf)
        if not full_name.strip():
            return firm_page(request, user, error="Podaj imię i nazwisko prawnika.")
        with services.sessions() as db:
            lawyer = db.get(Lawyer, int(lawyer_id)) if lawyer_id else Lawyer()
            lawyer.full_name, lawyer.title = full_name.strip()[:255], title.strip()[:64]
            lawyer.registry_no = registry_no.strip()[:64]
            lawyer.user_id = int(user_id) if user_id else None
            lawyer.active = active == "yes"
            db.add(lawyer)
            db.flush()
            services.audit(db, user.id, None, f"lawyer_save:{lawyer.id}", ip(request))
            db.commit()
        return RedirectResponse("/admin/firm?saved=1#lawyers", status_code=303)

    @app.post("/cases/{case_id}/delete")
    def case_delete(request: Request, case_id: str, user: UserDep, csrf: Csrf):
        check_csrf(request, csrf)
        services.delete_case(case_id, user.id, ip(request))
        return RedirectResponse("/", status_code=303)

    # --- admin -------------------------------------------------------------------------

    @app.get("/admin/users", response_class=HTMLResponse)
    def admin_users(request: Request, user: AdminDep):
        with services.sessions() as db:
            users = list(db.scalars(select(User).order_by(User.email)))
        return render(request, "admin_users.html", user, users=users)

    @app.post("/admin/users")
    def admin_user_create(request: Request, user: AdminDep, csrf: Csrf,
                          email: Annotated[str, Form()], password: Annotated[str, Form()],
                          role: Annotated[str, Form()] = "lawyer"):
        check_csrf(request, csrf)
        if role not in ("lawyer", "admin"):
            raise HTTPException(status_code=400)
        try:
            new = create_user(services, email, password, role)
        except ValueError as exc:
            with services.sessions() as db:
                users = list(db.scalars(select(User).order_by(User.email)))
            return render(request, "admin_users.html", user, users=users, error=str(exc))
        with services.sessions() as db:
            services.audit(db, user.id, None, f"user_create:{new.id}", ip(request))
            db.commit()
            users = list(db.scalars(select(User).order_by(User.email)))
        uri = totp_uri(new.totp_secret, new.email)
        return render(request, "admin_users.html", user, users=users, created=new, totp_uri=uri,
                      qr_svg=qr_svg(uri))

    @app.post("/admin/users/{user_id}/toggle")
    def admin_user_toggle(request: Request, user_id: int, user: AdminDep, csrf: Csrf):
        check_csrf(request, csrf)
        with services.sessions() as db:
            target = db.get(User, user_id)
            if target is None or target.id == user.id:
                raise HTTPException(status_code=400)
            target.active = not target.active
            services.audit(db, user.id, None, f"user_toggle:{user_id}:{target.active}", ip(request))
            db.commit()
        return RedirectResponse("/admin/users", status_code=303)

    @app.get("/admin/log", response_class=HTMLResponse)
    def admin_log(request: Request, user: AdminDep, case_id: str | None = None):
        with services.sessions() as db:
            q = select(AccessLog).order_by(AccessLog.at.desc()).limit(500)
            if case_id:
                q = q.where(AccessLog.case_id == case_id)
            entries = list(db.scalars(q))
            emails = {u.id: u.email for u in db.scalars(select(User))}
        return render(request, "admin_log.html", user, entries=entries, emails=emails, case_id=case_id)

    @app.get("/healthz")
    def healthz():
        return Response("ok", media_type="text/plain")

    return app


def create_user(services: Services, email: str, password: str, role: str = "lawyer") -> User:
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("nieprawidłowy e-mail")
    with services.sessions() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise ValueError("użytkownik już istnieje")
        user = User(email=email, password_hash=hash_password(password), totp_secret=new_totp_secret(), role=role)
        db.add(user)
        db.commit()
        return user


def qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def build() -> FastAPI:  # pragma: no cover - production entry point
    """uvicorn app.main:build --factory"""
    from app.factory import build_services

    return create_app(build_services())
