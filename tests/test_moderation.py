from datetime import timedelta
from urllib.parse import unquote

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.accounts import utcnow
from app.db import SessionLocal, engine
from app.friends import relation_status
from app.main import app
from app.models import ClubMessage, DirectMessage, ModerationEvent, Report, ReportCase, User, UserBlock
from app.moderation import (
    AllowAllProvider,
    Verdict,
    apply_violation,
    counting_violation_count,
    reverse_event,
    set_provider,
)
from app.reports import load_snapshot
from tests.test_app import register_active
from tests.test_dm import _befriend
from tests.test_suggestions import _grant_site_admin, _user_id

REPORT_NOTE = "Descrevo a situação com contexto suficiente para a análise justa."


def test_safety_schema_is_additive():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "user_blocks",
        "report_cases",
        "reports",
        "report_case_users",
        "report_case_messages",
        "report_attachments",
        "moderation_events",
        "appeals",
        "appeal_attachments",
    } <= tables
    users = {column["name"] for column in inspector.get_columns("users")}
    assert {"suspended_until", "banned_at", "had_progression_suspend"} <= users
    messages = {column["name"] for column in inspector.get_columns("club_messages")}
    assert "removed_at" in messages


def test_report_groups_snapshot_and_privacy():
    author = TestClient(app)
    one = TestClient(app)
    two = TestClient(app)
    accused = TestClient(app)
    register_active(author, "rep_author", "rep.author@example.com")
    register_active(one, "rep_one", "rep.one@example.com")
    register_active(two, "rep_two", "rep.two@example.com")
    register_active(accused, "rep_target", "rep.target@example.com")
    created = author.post("/clubs", data={"name": "Clube Denuncia"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    author.post(f"/clubs/{club_id}/mensagens", data={"body": "mensagem denunciavel"}, follow_redirects=False)
    db = SessionLocal()
    try:
        message = db.scalar(select(ClubMessage).where(ClubMessage.body == "mensagem denunciavel"))
        message_id = message.id
        author_id = message.user_id
        club = message.club_id
    finally:
        db.close()
    db = SessionLocal()
    try:
        from app.models import Club

        code = db.get(Club, club).join_code
    finally:
        db.close()
    for client in (one, two, accused):
        client.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)

    first = one.post(
        "/denunciar",
        data={"tipo": "club_message", "alvo": str(message_id), "reason": "harassment", "explanation": REPORT_NOTE, "next": "/"},
        follow_redirects=False,
    )
    assert first.status_code == 303
    assert "/denunciar/ok" in first.headers["location"]
    second = two.post(
        "/denunciar",
        data={"tipo": "club_message", "alvo": str(message_id), "reason": "spam", "explanation": REPORT_NOTE, "next": "/"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    db = SessionLocal()
    try:
        cases = list(db.scalars(select(ReportCase).where(ReportCase.target_key == f"club_message:{message_id}")))
        assert len(cases) == 1
        case = cases[0]
        assert case.report_count == 2
        assert case.reported_user_id == author_id
        snap = load_snapshot(case.snapshot_json)
        assert snap["body"] == "mensagem denunciavel"
        reports = list(db.scalars(select(Report).where(Report.case_id == case.id)))
        assert {row.reporter_id for row in reports} == {_user_id("rep.one@example.com"), _user_id("rep.two@example.com")}
        case_id = case.id
    finally:
        db.close()

    author.post(f"/clubs/{club_id}/mensagens/{message_id}/apagar", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, message_id) is None
        case = db.get(ReportCase, case_id)
        assert load_snapshot(case.snapshot_json)["body"] == "mensagem denunciavel"
    finally:
        db.close()

    profile = accused.get("/u/rep_one")
    assert profile.status_code == 200
    assert "rep.one@example.com" not in profile.text
    admin_page = accused.get("/admin/denuncias", follow_redirects=False)
    assert admin_page.status_code == 303
    assert "Acesso restrito" in unquote(admin_page.headers["location"]) or admin_page.headers["location"].startswith("/")


def test_report_does_not_punish_or_autoban():
    host = TestClient(app)
    guest = TestClient(app)
    extra = TestClient(app)
    register_active(host, "np_host", "np.host@example.com")
    register_active(guest, "np_guest", "np.guest@example.com")
    register_active(extra, "np_extra", "np.extra@example.com")
    created = host.post("/clubs", data={"name": "Clube NP"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    host.post(f"/clubs/{club_id}/mensagens", data={"body": "ainda no ar"}, follow_redirects=False)
    db = SessionLocal()
    try:
        from app.models import Club

        code = db.get(Club, club_id).join_code
        message_id = db.scalar(select(ClubMessage.id).where(ClubMessage.body == "ainda no ar"))
        host_id = _user_id("np.host@example.com")
    finally:
        db.close()
    guest.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    extra.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    guest.post("/denunciar", data={"tipo": "club_message", "alvo": str(message_id), "reason": "spam", "explanation": REPORT_NOTE, "next": "/"}, follow_redirects=False)
    extra.post("/denunciar", data={"tipo": "club_message", "alvo": str(message_id), "reason": "hate", "explanation": REPORT_NOTE, "next": "/"}, follow_redirects=False)
    db = SessionLocal()
    try:
        user = db.get(User, host_id)
        assert user.banned_at is None
        assert user.suspended_until is None
        assert counting_violation_count(db, host_id) == 0
    finally:
        db.close()


def test_block_unfriend_dm_mention_notifications_and_club_chat():
    a = TestClient(app)
    b = TestClient(app)
    register_active(a, "blk_a", "blk.a@example.com")
    register_active(b, "blk_b", "blk.b@example.com")
    _befriend(a, b, "blk_a", "blk_b")
    created = a.post("/clubs", data={"name": "Clube Bloco"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        from app.models import Club

        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    b.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    b.post(f"/clubs/{club_id}/mensagens", data={"body": "oi do bloqueado"}, follow_redirects=False)
    a.post("/mensagens/blk_b", data={"body": "historico fica"}, follow_redirects=False)

    blocked = a.post("/u/blk_b/bloquear", data={"next": "/u/blk_b"}, follow_redirects=False)
    assert blocked.status_code == 303
    db = SessionLocal()
    try:
        a_id, b_id = _user_id("blk.a@example.com"), _user_id("blk.b@example.com")
        assert relation_status(db, a_id, b_id) == "none"
        assert db.scalar(select(UserBlock).where(UserBlock.blocker_id == a_id, UserBlock.blocked_id == b_id))
        assert db.scalar(select(DirectMessage).where(DirectMessage.body == "historico fica"))
    finally:
        db.close()

    invite = b.post("/amigos/blk_a/convidar", data={"next": "/amigos"}, follow_redirects=False)
    assert invite.status_code == 303
    assert "bloqueio" in unquote(invite.headers["location"]).lower() or "error=" in invite.headers["location"]
    dm_a = a.post("/mensagens/blk_b", data={"body": "depois do bloqueio"}, follow_redirects=False)
    dm_b = b.post("/mensagens/blk_a", data={"body": "resposta bloqueada"}, follow_redirects=False)
    assert dm_a.status_code == 303
    assert dm_b.status_code == 303

    mention = b.post(f"/clubs/{club_id}/mensagens", data={"body": "oi @blk_a"}, follow_redirects=False)
    assert mention.status_code == 303
    assert "mencionar" in unquote(mention.headers["location"]).lower()

    chat = a.get(f"/clubs/{club_id}?aba=chat")
    assert "Mensagem de usuário bloqueado" in chat.text
    assert "oi do bloqueado" in chat.text
    agenda = a.get(f"/clubs/{club_id}?aba=agendamentos")
    assert agenda.status_code == 200
    assert "Agendamentos" in agenda.text

    settings = a.get("/conta")
    assert "Usuários bloqueados" in settings.text
    assert "@blk_b" in settings.text
    a.post("/conta/bloqueios/blk_b/remover", follow_redirects=False)
    db = SessionLocal()
    try:
        a_id, b_id = _user_id("blk.a@example.com"), _user_id("blk.b@example.com")
        assert relation_status(db, a_id, b_id) == "none"
        assert db.scalar(select(UserBlock.id).where(UserBlock.blocker_id == a_id)) is None
    finally:
        db.close()


def test_warning_ladder_suspend_ban_and_reversal():
    client = TestClient(app)
    admin = TestClient(app)
    register_active(client, "warn_user", "warn.user@example.com")
    register_active(admin, "warn_admin", "warn.admin@example.com")
    _grant_site_admin("warn.admin@example.com")
    user_id = _user_id("warn.user@example.com")
    admin_id = _user_id("warn.admin@example.com")

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        actor = db.get(User, admin_id)
        e1, msg1 = apply_violation(db, user, category="hate", origin="admin", evidence="um", counts=True, actor_id=actor.id)
        assert e1.warning_number == 1 and "Aviso 1 de 3" in msg1
        e2, msg2 = apply_violation(db, user, category="hate", origin="admin", evidence="dois", counts=True, actor_id=actor.id)
        assert e2.warning_number == 2
        e3, msg3 = apply_violation(db, user, category="hate", origin="admin", evidence="tres", counts=True, actor_id=actor.id)
        assert e3.warning_number == 3
        assert "30 dias" in msg3
        e4, msg4 = apply_violation(db, user, category="hate", origin="admin", evidence="quatro", counts=True, actor_id=actor.id)
        assert e4.action == "suspend"
        assert user.had_progression_suspend is True
        user.suspended_until = utcnow() - timedelta(days=1)
        e5, msg5 = apply_violation(db, user, category="hate", origin="admin", evidence="cinco", counts=True, actor_id=actor.id)
        assert e5.action == "ban"
        assert user.banned_at is not None
        db.commit()
        event_id = e2.id
        ban_id = e5.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        actor = db.get(User, admin_id)
        event = db.get(ModerationEvent, event_id)
        reverse_event(db, event, actor)
        db.commit()
        assert counting_violation_count(db, user_id) == 4
        user = db.get(User, user_id)
        assert user.banned_at is not None
        ban = db.get(ModerationEvent, ban_id)
        reverse_event(db, ban, actor)
        db.commit()
        user = db.get(User, user_id)
        assert user.banned_at is None
    finally:
        db.close()


def test_admin_report_actions_and_single_appeal():
    member = TestClient(app)
    reporter = TestClient(app)
    admin = TestClient(app)
    register_active(member, "adm_mem", "adm.mem@example.com")
    register_active(reporter, "adm_rep", "adm.rep@example.com")
    register_active(admin, "adm_mod", "adm.mod@example.com")
    _grant_site_admin("adm.mod@example.com")
    created = member.post("/clubs", data={"name": "Clube Admin Rep"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    member.post(f"/clubs/{club_id}/mensagens", data={"body": "alvo admin"}, follow_redirects=False)
    db = SessionLocal()
    try:
        from app.models import Club

        code = db.get(Club, club_id).join_code
        message_id = db.scalar(select(ClubMessage.id).where(ClubMessage.body == "alvo admin"))
    finally:
        db.close()
    reporter.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    reporter.post(
        "/denunciar",
        data={"tipo": "club_message", "alvo": str(message_id), "reason": "hate", "explanation": REPORT_NOTE, "next": "/"},
        follow_redirects=False,
    )
    listing = admin.get("/admin/denuncias")
    assert listing.status_code == 200
    assert "Pendentes" in listing.text
    assert "adm_mem" in listing.text
    assert "@adm_rep" in listing.text
    db = SessionLocal()
    try:
        case_id = db.scalar(select(ReportCase.id).where(ReportCase.target_key == f"club_message:{message_id}"))
        member_id = _user_id("adm.mem@example.com")
    finally:
        db.close()
    warned = admin.post(f"/admin/denuncias/{case_id}/advertir", follow_redirects=False)
    assert warned.status_code == 303
    db = SessionLocal()
    try:
        assert counting_violation_count(db, member_id) == 1
        event = db.scalar(select(ModerationEvent).where(ModerationEvent.user_id == member_id))
        event_id = event.id
    finally:
        db.close()
    short = member.post(
        f"/contestacoes/{event_id}",
        data={"reason": "context", "explanation": "curto"},
        follow_redirects=False,
    )
    assert short.status_code == 303
    assert "error=" in short.headers["location"]
    ok = member.post(
        f"/contestacoes/{event_id}",
        data={
            "reason": "auto_error",
            "explanation": "A mensagem foi interpretada fora do contexto da conversa do clube.",
        },
        follow_redirects=False,
    )
    assert ok.status_code == 303
    again = member.post(
        f"/contestacoes/{event_id}",
        data={
            "reason": "other",
            "explanation": "Segunda tentativa de contestação da mesma penalidade aplicada.",
        },
        follow_redirects=False,
    )
    assert "já solicitou" in unquote(again.headers["location"]).lower() or "error=" in again.headers["location"]
    db = SessionLocal()
    try:
        from app.models import Appeal

        appeal_id = db.scalar(select(Appeal.id).where(Appeal.event_id == event_id))
    finally:
        db.close()
    keep = admin.post(f"/admin/contestacoes/{appeal_id}/manter", follow_redirects=False)
    assert keep.status_code == 303
    db = SessionLocal()
    try:
        assert counting_violation_count(db, member_id) == 1
    finally:
        db.close()

    denied = reporter.get("/admin/denuncias", follow_redirects=False)
    assert denied.status_code == 303


def test_community_rules_and_enter_default_do_not_overwrite():
    page = TestClient(app).get("/regras")
    assert page.status_code == 200
    assert "Avisos, suspensão e banimento" in page.text
    host = TestClient(app)
    register_active(host, "pref_keep", "pref.keep@example.com")
    host.post("/conta/conversas", data={"enter_sends": "0"}, headers={"x-watchclub-pref": "1"})
    again = host.get("/")
    assert again.status_code == 200
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "pref.keep@example.com"))
        assert user.enter_sends is False
    finally:
        db.close()


def test_high_confidence_provider_counts_once():
    class HighConfidence(AllowAllProvider):
        def moderate_text(self, text: str, *, surface: str) -> Verdict:
            if "WC_CONFIDENT_VIOLATION" in (text or ""):
                return Verdict(allowed=False, category="hate", counts=True, confidence="high")
            return Verdict(allowed=True)

    set_provider(HighConfidence())
    try:
        host = TestClient(app)
        register_active(host, "mod_auto", "mod.auto@example.com")
        created = host.post("/clubs", data={"name": "Clube Auto"}, follow_redirects=False)
        club_id = int(created.headers["location"].rsplit("/", 1)[-1])
        blocked = host.post(
            f"/clubs/{club_id}/mensagens",
            data={"body": "WC_CONFIDENT_VIOLATION no chat"},
            follow_redirects=False,
        )
        assert blocked.status_code == 303
        assert "regras de segurança" in unquote(blocked.headers["location"]).lower()
        db = SessionLocal()
        try:
            user_id = _user_id("mod.auto@example.com")
            assert counting_violation_count(db, user_id) == 1
            assert db.scalar(select(ClubMessage).where(ClubMessage.body.contains("WC_CONFIDENT_VIOLATION"))) is None
        finally:
            db.close()
    finally:
        set_provider(None)


def test_safety_hub_club_shortcuts_and_privacy():
    owner = TestClient(app)
    member = TestClient(app)
    outsider = TestClient(app)
    register_active(owner, "hub_owner", "hub.owner@example.com")
    register_active(member, "hub_mem", "hub.mem@example.com")
    register_active(outsider, "hub_out", "hub.out@example.com")
    created = owner.post("/clubs", data={"name": "Clube Hub"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    db = SessionLocal()
    try:
        from app.models import Club

        code = db.get(Club, club_id).join_code
        owner_id = _user_id("hub.owner@example.com")
        member_id = _user_id("hub.mem@example.com")
    finally:
        db.close()
    member.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)
    owner.post(f"/clubs/{club_id}/mensagens", data={"body": "hub alvo"}, follow_redirects=False)
    db = SessionLocal()
    try:
        message_id = db.scalar(select(ClubMessage.id).where(ClubMessage.body == "hub alvo"))
    finally:
        db.close()
    member.post(
        "/denunciar",
        data={"tipo": "club_message", "alvo": str(message_id), "reason": "spam", "explanation": REPORT_NOTE, "next": "/"},
        follow_redirects=False,
    )
    outsider.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(owner_id), "reason": "hate", "explanation": REPORT_NOTE, "next": "/"},
        follow_redirects=False,
    )

    guest = TestClient(app)
    locked = guest.get("/seguranca", follow_redirects=False)
    assert locked.status_code == 303
    assert locked.headers["location"] == "/login"

    hub = member.get("/seguranca")
    assert hub.status_code == 200
    assert "Fazer uma denúncia" in hub.text
    assert "Minhas denúncias" in hub.text
    assert "Usuários bloqueados" in hub.text
    assert "Avisos e contestações" in hub.text
    assert "Spam" in hub.text
    assert "@hub_out" not in hub.text
    assert "hub.out@example.com" not in hub.text
    assert "Pendentes" not in hub.text
    assert "Advertir" not in hub.text
    other_hub = outsider.get("/seguranca")
    assert "Spam" not in other_hub.text
    assert "Discurso de ódio" in other_hub.text or "ódio" in other_hub.text.lower()

    missing = member.post("/seguranca/denunciar/usuario", data={"username": "nao_existe"}, follow_redirects=False)
    assert missing.status_code == 303
    assert "error=" in missing.headers["location"]
    self_rep = member.post("/seguranca/denunciar/usuario", data={"username": "hub_mem"}, follow_redirects=False)
    assert "error=" in self_rep.headers["location"]
    started = member.post("/seguranca/denunciar/usuario", data={"username": "hub_owner"}, follow_redirects=False)
    assert started.status_code == 303
    assert started.headers["location"] == "/seguranca/denunciar/usuario"
    pick = member.get("/seguranca/denunciar/usuario")
    assert "@hub_owner" in pick.text
    continued = member.post("/seguranca/denunciar/usuario", data={"action": "continue"}, follow_redirects=False)
    assert f"/denunciar?tipo=user&id={owner_id}" in continued.headers["location"]

    club_start = member.post("/seguranca/denunciar/clube", data={"club_id": str(club_id)}, follow_redirects=False)
    assert club_start.status_code == 303
    assert f"/denunciar?tipo=club&id={club_id}" in club_start.headers["location"]
    outsider_club = outsider.post("/seguranca/denunciar/clube", data={"club_id": str(club_id)}, follow_redirects=False)
    assert "error=" in outsider_club.headers["location"]

    club_page = member.get(f"/clubs/{club_id}?aba=denuncias")
    assert club_page.status_code == 200
    assert "Denunciar membro" in club_page.text
    assert "Denunciar uma mensagem" in club_page.text
    assert "Denunciar o clube" in club_page.text
    assert "use Denunciar nas ações da mensagem" in club_page.text
    chat = member.get(f"/clubs/{club_id}?aba=chat")
    assert ">Denunciar<" in chat.text or "Denunciar" in chat.text

    bad_member = member.post(
        f"/clubs/{club_id}/denuncias/membro",
        data={"member_user_id": str(_user_id("hub.out@example.com"))},
        follow_redirects=False,
    )
    assert bad_member.status_code == 303
    assert "aba=denuncias" in bad_member.headers["location"]
    good_member = member.post(
        f"/clubs/{club_id}/denuncias/membro",
        data={"member_user_id": str(owner_id)},
        follow_redirects=False,
    )
    assert f"/denunciar?tipo=user&id={owner_id}" in good_member.headers["location"]

    outsider_club_page = outsider.get(f"/clubs/{club_id}?aba=denuncias", follow_redirects=False)
    assert outsider_club_page.status_code in {200, 303}
    if outsider_club_page.status_code == 200:
        assert "Denunciar membro" not in outsider_club_page.text

    block = member.post("/u/hub_owner/bloquear", data={"next": "/seguranca"}, follow_redirects=False)
    assert block.status_code == 303
    hub_blocked = member.get("/seguranca")
    assert "@hub_owner" in hub_blocked.text
    settings = member.get("/conta")
    assert "@hub_owner" in settings.text
    member.post("/conta/bloqueios/hub_owner/remover", data={"next": "/seguranca"}, follow_redirects=False)
    assert "@hub_owner" not in member.get("/seguranca").text

    admin_denied = member.get("/admin/denuncias", follow_redirects=False)
    assert admin_denied.status_code == 303
    regras = member.get("/regras")
    assert regras.status_code == 200
    home = member.get("/")
    assert 'aria-label="Segurança e denúncias"' in home.text
    assert 'href="/regras"' in home.text
    assert 'aria-label="Sobre"' not in home.text
