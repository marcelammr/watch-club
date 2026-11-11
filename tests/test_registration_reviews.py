from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app.accounts import utcnow
from app.auth0_oidc import Auth0Identity
from app.db import SessionLocal, engine
from app.main import app
from app.models import Notification, RegistrationRequest, RegistrationReview, User
from app.notifications import TYPE_REGISTRATION_REVIEW, unread_count
from app.registrations import REVIEW_PENDING, STATUS_REJECTED, create_registration_review
from app.schema import migrate_schema
from tests.test_admin_registrations import _grant_site_admin, _onboard
from tests.test_app import register_active
from tests.test_auth0 import _enable_auth0, _start_callback


def test_review_schema_and_unique_indexes():
    migrate_schema()
    inspector = inspect(engine)
    assert "registration_reviews" in inspector.get_table_names()
    cols = {column["name"] for column in inspector.get_columns("registration_reviews")}
    assert {
        "id",
        "registration_request_id",
        "user_id",
        "message",
        "status",
        "created_at",
        "decided_at",
        "decided_by_user_id",
    } <= cols
    with engine.connect() as connection:
        review_index = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ix_registration_reviews_request_id'")
        ).scalar()
        notice_index = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE name = 'ix_notifications_one_registration_review_per_admin'"
            )
        ).scalar()
    assert review_index
    assert notice_index


def test_new_signup_cannot_enter_rejection_review(monkeypatch):
    _enable_auth0(monkeypatch)
    admin = TestClient(app)
    register_active(admin, "rev_admin", "rev.admin@example.com")
    _grant_site_admin("rev.admin@example.com")
    person = TestClient(app)
    created = _onboard(person, "auth0|rev-new", "rev.new@example.com", "Rev Novo", "rev_novo")
    assert created.headers["location"] == "/"
    asked = person.get("/auth/revisao", follow_redirects=False)
    assert asked.status_code == 303
    assert asked.headers["location"] == "/"
    submitted = person.post("/auth/revisao", data={"message": "Quero revisão"}, follow_redirects=False)
    assert submitted.status_code == 303
    assert submitted.headers["location"] == "/"
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "rev.new@example.com"))
        status, review_id = create_registration_review(db, user.id, "Quero revisão")
        assert status is None
        assert review_id is None
        assert db.scalar(select(RegistrationReview).where(RegistrationReview.user_id == user.id)) is None
        admin_id = db.scalar(select(User.id).where(User.email == "rev.admin@example.com"))
        assert unread_count(db, admin_id) == 0
    finally:
        db.close()
    listing = admin.get("/admin/cadastros/revisoes/1", follow_redirects=False)
    assert listing.status_code == 303
    assert listing.headers["location"] == "/admin/sugestoes"
    kept = admin.post("/admin/cadastros/revisoes/1/aprovar-acesso", follow_redirects=False)
    assert kept.status_code == 303
    assert kept.headers["location"] == "/admin/sugestoes"


def test_historical_rejected_review_rows_do_not_break_app(monkeypatch):
    _enable_auth0(monkeypatch)
    db = SessionLocal()
    try:
        user = User(
            name="Hist Revisão",
            username="hist_rev",
            username_key="hist_rev",
            email="hist.rev@example.com",
            password_hash="",
            is_active=False,
            auth0_sub="auth0|hist-rev",
        )
        db.add(user)
        db.flush()
        request = RegistrationRequest(user_id=user.id, status=STATUS_REJECTED, decided_at=utcnow())
        db.add(request)
        db.flush()
        review = RegistrationReview(
            registration_request_id=request.id,
            user_id=user.id,
            message="Pedido histórico",
            status=REVIEW_PENDING,
        )
        db.add(review)
        db.commit()
        user_id = user.id
        review_id = review.id
    finally:
        db.close()
    migrate_schema()
    http = TestClient(app)
    callback = _start_callback(
        http,
        Auth0Identity(sub="auth0|hist-rev", email="hist.rev@example.com", email_verified=True),
    )
    assert callback.headers["location"] == "/auth/revisao-solicitada"
    page = http.get("/auth/revisao-solicitada")
    assert page.status_code == 200
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user.is_active is False
        kept = db.get(RegistrationReview, review_id)
        assert kept.message == "Pedido histórico"
        assert kept.status == REVIEW_PENDING
        notes = list(db.scalars(select(Notification).where(Notification.type == TYPE_REGISTRATION_REVIEW)))
        assert notes == []
    finally:
        db.close()
    admin = TestClient(app)
    register_active(admin, "hist_rev_adm", "hist.rev.adm@example.com")
    _grant_site_admin("hist.rev.adm@example.com")
    opened = admin.get(f"/admin/cadastros/revisoes/{review_id}", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/admin/sugestoes"
    approved = admin.post(
        f"/admin/cadastros/revisoes/{review_id}/aprovar-acesso",
        follow_redirects=False,
    )
    assert approved.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(User, user_id).is_active is False
        assert db.get(RegistrationReview, review_id).status == REVIEW_PENDING
    finally:
        db.close()
