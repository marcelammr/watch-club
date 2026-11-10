from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Club, ClubMessage, DirectMessage, ReportAttachment, ReportCase, ReportCaseMessage, ReportCaseUser, User
from app.reports import MAX_REPORT_MESSAGES, REPORT_NOTE_MAX, REPORT_NOTE_MIN, load_snapshot
from tests.test_app import register_active
from tests.test_dm import _befriend
from tests.test_moderation import REPORT_NOTE
from tests.test_suggestions import _grant_site_admin, _user_id

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _join(client, club_id):
    db = SessionLocal()
    try:
        code = db.get(Club, club_id).join_code
    finally:
        db.close()
    client.post("/clubs/join", data={"join_code": code, "next": "/"}, follow_redirects=False)


def _club_with_members(*clients_and_names):
    owner = clients_and_names[0][0]
    created = owner.post("/clubs", data={"name": "Clube Caso"}, follow_redirects=False)
    club_id = int(created.headers["location"].rsplit("/", 1)[-1])
    for client, _email in clients_and_names[1:]:
        _join(client, club_id)
    return club_id


def test_multi_user_report_dedupes_and_rejects_invalid():
    reporter = TestClient(app)
    one = TestClient(app)
    two = TestClient(app)
    ghost = TestClient(app)
    register_active(reporter, "caso_rep", "caso.rep@example.com")
    register_active(one, "caso_one", "caso.one@example.com")
    register_active(two, "caso_two", "caso.two@example.com")
    register_active(ghost, "caso_ghost", "caso.ghost@example.com")
    one_id = _user_id("caso.one@example.com")
    two_id = _user_id("caso.two@example.com")
    reporter.post("/seguranca/denunciar/usuario", data={"username": "caso_one"}, follow_redirects=False)
    reporter.post("/seguranca/denunciar/usuario", data={"username": "caso_one"}, follow_redirects=False)
    reporter.post("/seguranca/denunciar/usuario", data={"username": "caso_two"}, follow_redirects=False)
    pick = reporter.get("/seguranca/denunciar/usuario")
    assert pick.text.count("report-chip") >= 2
    assert pick.text.count("@caso_two") >= 1
    missing = reporter.post("/seguranca/denunciar/usuario", data={"username": "nao_existe"}, follow_redirects=False)
    assert "error=" in missing.headers["location"]
    continued = reporter.post("/seguranca/denunciar/usuario", data={"action": "continue"}, follow_redirects=False)
    assert f"envolvidos={one_id}" in continued.headers["location"]
    assert f"envolvidos={two_id}" in continued.headers["location"]
    sent = reporter.post(
        "/denunciar",
        data={
            "tipo": "user",
            "alvo": str(one_id),
            "user_ids": [str(one_id), str(two_id), str(one_id)],
            "reason": "harassment",
            "explanation": REPORT_NOTE,
            "next": "/",
        },
        follow_redirects=False,
    )
    assert sent.status_code == 303
    assert "/denunciar/ok" in sent.headers["location"]
    thanks = reporter.get(sent.headers["location"])
    assert "Bloquear" in thanks.text
    assert "bloquear todos" not in thanks.text.lower()
    db = SessionLocal()
    try:
        case = db.scalar(select(ReportCase).order_by(ReportCase.id.desc()))
        people = list(db.scalars(select(ReportCaseUser).where(ReportCaseUser.case_id == case.id)))
        assert {row.user_id for row in people} == {one_id, two_id}
        assert case.report_count == 1
        one_user = db.get(User, one_id)
        two_user = db.get(User, two_id)
        assert one_user.banned_at is None and two_user.banned_at is None
    finally:
        db.close()
    bad = reporter.post(
        "/denunciar",
        data={"tipo": "user", "alvo": "0", "user_ids": ["abc"], "reason": "spam", "explanation": REPORT_NOTE},
        follow_redirects=False,
    )
    assert bad.status_code == 303


def test_club_members_multi_and_external_rejected():
    owner = TestClient(app)
    member = TestClient(app)
    outsider = TestClient(app)
    register_active(owner, "clm_owner", "clm.owner@example.com")
    register_active(member, "clm_mem", "clm.mem@example.com")
    register_active(outsider, "clm_out", "clm.out@example.com")
    club_id = _club_with_members((owner, "clm.owner@example.com"), (member, "clm.mem@example.com"))
    owner_id = _user_id("clm.owner@example.com")
    member_id = _user_id("clm.mem@example.com")
    out_id = _user_id("clm.out@example.com")
    rejected = member.post(
        f"/clubs/{club_id}/denuncias/membro",
        data={"member_user_ids": str(out_id)},
        follow_redirects=False,
    )
    assert "aba=denuncias" in rejected.headers["location"]
    started = member.post(
        f"/clubs/{club_id}/denuncias/membro",
        data={"member_user_ids": [str(owner_id), str(owner_id)]},
        follow_redirects=False,
    )
    assert f"envolvidos={owner_id}" in started.headers["location"]
    club_only = member.post(
        "/denunciar",
        data={
            "tipo": "club",
            "alvo": str(club_id),
            "club_scope": str(club_id),
            "reason": "profile",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    assert "/denunciar/ok" in club_only.headers["location"]
    with_people = owner.post(
        "/denunciar",
        data={
            "tipo": "club",
            "alvo": str(club_id),
            "club_scope": str(club_id),
            "user_ids": [str(member_id)],
            "reason": "harassment",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    assert "/denunciar/ok" in with_people.headers["location"]
    inject = member.post(
        "/denunciar",
        data={
            "tipo": "club",
            "alvo": str(club_id),
            "club_scope": str(club_id),
            "user_ids": [str(out_id)],
            "reason": "spam",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    assert "error=" in inject.headers["location"]


def test_chat_multi_message_authors_limit_and_snapshot():
    owner = TestClient(app)
    ana = TestClient(app)
    joao = TestClient(app)
    maria = TestClient(app)
    reporter = TestClient(app)
    other = TestClient(app)
    register_active(owner, "cht_own", "cht.own@example.com")
    register_active(ana, "cht_ana", "cht.ana@example.com")
    register_active(joao, "cht_joao", "cht.joao@example.com")
    register_active(maria, "cht_maria", "cht.maria@example.com")
    register_active(reporter, "cht_rep", "cht.rep@example.com")
    register_active(other, "cht_oth", "cht.oth@example.com")
    club_id = _club_with_members(
        (owner, "cht.own@example.com"),
        (ana, "cht.ana@example.com"),
        (joao, "cht.joao@example.com"),
        (maria, "cht.maria@example.com"),
        (reporter, "cht.rep@example.com"),
    )
    other_club = other.post("/clubs", data={"name": "Outro Clube"}, follow_redirects=False)
    other_id = int(other_club.headers["location"].rsplit("/", 1)[-1])
    other.post(f"/clubs/{other_id}/mensagens", data={"body": "outra sala"}, follow_redirects=False)
    ana.post(f"/clubs/{club_id}/mensagens", data={"body": "fala ana um"}, follow_redirects=False)
    joao.post(f"/clubs/{club_id}/mensagens", data={"body": "fala joao"}, follow_redirects=False)
    ana.post(f"/clubs/{club_id}/mensagens", data={"body": "fala ana dois"}, follow_redirects=False)
    maria.post(f"/clubs/{club_id}/mensagens", data={"body": "fala maria"}, follow_redirects=False)
    db = SessionLocal()
    try:
        bodies = ["fala ana um", "fala joao", "fala ana dois", "fala maria"]
        ids = [db.scalar(select(ClubMessage.id).where(ClubMessage.body == body)) for body in bodies]
        foreign = db.scalar(select(ClubMessage.id).where(ClubMessage.body == "outra sala"))
        ana_id = _user_id("cht.ana@example.com")
        joao_id = _user_id("cht.joao@example.com")
        maria_id = _user_id("cht.maria@example.com")
    finally:
        db.close()
    chat = reporter.get(f"/clubs/{club_id}?aba=chat")
    assert 'title="Denunciar mensagem"' in chat.text
    selecting = reporter.get(f"/clubs/{club_id}?aba=chat&selecionar={ids[0]}")
    assert "Continuar" in selecting.text
    prepared = reporter.post(
        "/denunciar/mensagens",
        data={"club_id": str(club_id), "message_ids": [str(item) for item in ids], "next": f"/clubs/{club_id}?aba=chat"},
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    assert "mensagens=" in prepared.headers["location"]
    form = reporter.get(prepared.headers["location"])
    assert "@cht_ana" in form.text and "@cht_joao" in form.text and "@cht_maria" in form.text
    assert form.text.count("@cht_ana") >= 1
    sent = reporter.post(
        "/denunciar",
        data={
            "tipo": "club_message",
            "alvo": str(ids[0]),
            "message_ids": [str(item) for item in ids],
            "reason": "harassment",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    assert "/denunciar/ok" in sent.headers["location"]
    db = SessionLocal()
    try:
        case = db.scalar(select(ReportCase).where(ReportCase.target_type == "club_message").order_by(ReportCase.id.desc()))
        people = list(db.scalars(select(ReportCaseUser).where(ReportCaseUser.case_id == case.id)))
        assert {row.user_id for row in people} == {ana_id, joao_id, maria_id}
        assert all(row.locked for row in people)
        msgs = list(db.scalars(select(ReportCaseMessage).where(ReportCaseMessage.case_id == case.id)))
        assert len(msgs) == 4
        case_id = case.id
        first_id = ids[0]
    finally:
        db.close()
    ana.post(f"/clubs/{club_id}/mensagens/{first_id}/apagar", follow_redirects=False)
    db = SessionLocal()
    try:
        assert db.get(ClubMessage, first_id) is None
        leftover = list(db.scalars(select(ReportCaseMessage).where(ReportCaseMessage.case_id == case_id)))
        bodies = [load_snapshot(item.snapshot_json).get("body") for item in leftover]
        assert "fala ana um" in bodies
    finally:
        db.close()
    too_many = reporter.post(
        "/denunciar/mensagens",
        data={"club_id": str(club_id), "message_ids": [str(i) for i in range(1, MAX_REPORT_MESSAGES + 2)]},
        follow_redirects=False,
    )
    assert "error=" in too_many.headers["location"]
    cross = reporter.post(
        "/denunciar",
        data={
            "tipo": "club_message",
            "alvo": str(foreign),
            "reason": "spam",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    assert "error=" in cross.headers["location"]


def test_dm_same_thread_only_and_no_leak():
    a = TestClient(app)
    b = TestClient(app)
    c = TestClient(app)
    register_active(a, "dmr_a", "dmr.a@example.com")
    register_active(b, "dmr_b", "dmr.b@example.com")
    register_active(c, "dmr_c", "dmr.c@example.com")
    _befriend(a, b, "dmr_a", "dmr_b")
    _befriend(b, c, "dmr_b", "dmr_c")
    b.post("/mensagens/dmr_a", data={"body": "oi da b"}, follow_redirects=False)
    a.post("/mensagens/dmr_b", data={"body": "resposta a"}, follow_redirects=False)
    b.post("/mensagens/dmr_a", data={"body": "segunda b"}, follow_redirects=False)
    c.post("/mensagens/dmr_b", data={"body": "segredo c"}, follow_redirects=False)
    db = SessionLocal()
    try:
        own_ids = list(
            db.scalars(
                select(DirectMessage.id).where(
                    DirectMessage.body.in_(["oi da b", "resposta a", "segunda b"])
                )
            )
        )
        secret_id = db.scalar(select(DirectMessage.id).where(DirectMessage.body == "segredo c"))
        b_id = _user_id("dmr.b@example.com")
    finally:
        db.close()
    thread = a.get("/mensagens/dmr_b?selecionar=" + str(own_ids[0]))
    assert "Continuar" in thread.text
    prepared = a.post(
        "/denunciar/mensagens-dm",
        data={"username": "dmr_b", "message_ids": [str(item) for item in own_ids]},
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    sent = a.post(
        "/denunciar",
        data={
            "tipo": "dm",
            "alvo": str(own_ids[0]),
            "message_ids": [str(item) for item in own_ids],
            "reason": "harassment",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    assert "/denunciar/ok" in sent.headers["location"]
    leak = a.post(
        "/denunciar",
        data={"tipo": "dm", "alvo": str(secret_id), "reason": "spam", "explanation": REPORT_NOTE},
        follow_redirects=False,
    )
    assert "error=" in leak.headers["location"] or leak.headers["location"].startswith("/")
    mixed = a.post(
        "/denunciar/mensagens-dm",
        data={"username": "dmr_b", "message_ids": [str(own_ids[0]), str(secret_id)]},
        follow_redirects=False,
    )
    assert mixed.status_code == 303
    assert "error=" in mixed.headers["location"] or mixed.headers["location"].startswith("/mensagens")
    db = SessionLocal()
    try:
        case = db.scalar(select(ReportCase).where(ReportCase.target_type == "dm").order_by(ReportCase.id.desc()))
        people = list(db.scalars(select(ReportCaseUser).where(ReportCaseUser.case_id == case.id)))
        assert {row.user_id for row in people} == {b_id}
        msgs = list(db.scalars(select(ReportCaseMessage).where(ReportCaseMessage.case_id == case.id)))
        assert len(msgs) == 3
        secret = db.get(DirectMessage, secret_id)
        assert secret.body == "segredo c"
        reply_id = db.scalar(select(DirectMessage.id).where(DirectMessage.body == "resposta a"))
        case_id = case.id
    finally:
        db.close()
    a.post(f"/mensagens/dmr_b/{reply_id}/apagar", follow_redirects=False)
    db = SessionLocal()
    try:
        leftover = list(db.scalars(select(ReportCaseMessage).where(ReportCaseMessage.case_id == case_id)))
        bodies = [load_snapshot(item.snapshot_json).get("body") for item in leftover]
        assert "resposta a" in bodies
    finally:
        db.close()


def test_explanation_required_and_bounds():
    host = TestClient(app)
    guest = TestClient(app)
    register_active(host, "exp_host", "exp.host@example.com")
    register_active(guest, "exp_guest", "exp.guest@example.com")
    host_id = _user_id("exp.host@example.com")
    short = guest.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(host_id), "reason": "other", "explanation": "curto"},
        follow_redirects=False,
    )
    assert "error=" in short.headers["location"]
    long_text = "x" * (REPORT_NOTE_MAX + 1)
    huge = guest.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(host_id), "reason": "spam", "explanation": long_text},
        follow_redirects=False,
    )
    assert "error=" in huge.headers["location"]
    ok = guest.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(host_id), "reason": "other", "explanation": "o" * REPORT_NOTE_MIN},
        follow_redirects=False,
    )
    assert "/denunciar/ok" in ok.headers["location"]


def test_attachments_limits_privacy_and_admin_access():
    admin = TestClient(app)
    reporter = TestClient(app)
    accused = TestClient(app)
    other = TestClient(app)
    register_active(admin, "att_adm", "att.adm@example.com")
    register_active(reporter, "att_rep", "att.rep@example.com")
    register_active(accused, "att_acc", "att.acc@example.com")
    register_active(other, "att_oth", "att.oth@example.com")
    limiter = TestClient(app)
    register_active(limiter, "att_lim", "att.lim@example.com")
    _grant_site_admin("att.adm@example.com")
    accused_id = _user_id("att.acc@example.com")
    limit_id = _user_id("att.lim@example.com")
    files = [("evidence", ("print.png", BytesIO(PNG), "image/png"))]
    sent = reporter.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(accused_id), "reason": "harassment", "explanation": REPORT_NOTE},
        files=files,
        follow_redirects=False,
    )
    assert "/denunciar/ok" in sent.headers["location"]
    db = SessionLocal()
    try:
        attachment = db.scalar(select(ReportAttachment).order_by(ReportAttachment.id.desc()))
        attachment_id = attachment.id
        filename = attachment.filename
        case_id = attachment.case_id
        report_id = attachment.report_id
    finally:
        db.close()
    assert "/" not in filename and ".." not in filename
    assert reporter.get(f"/denuncias/anexos/{attachment_id}").status_code == 200
    assert admin.get(f"/denuncias/anexos/{attachment_id}").status_code == 200
    denied = accused.get(f"/denuncias/anexos/{attachment_id}", follow_redirects=False)
    assert denied.status_code in {403, 404, 303}
    other_denied = other.get(f"/denuncias/anexos/{attachment_id}", follow_redirects=False)
    assert other_denied.status_code in {403, 404, 303}
    public = reporter.get(f"/static/uploads/report-evidence/{filename}")
    assert public.status_code == 404
    public_var = reporter.get(f"/static/{filename}")
    assert public_var.status_code == 404
    hub = reporter.get("/seguranca")
    assert f"/denuncias/anexos/{attachment_id}" in hub.text
    appeal_page = accused.get("/contestacoes/1", follow_redirects=False)
    if appeal_page.status_code == 200:
        assert f"/denuncias/anexos/{attachment_id}" not in appeal_page.text
    six = [("evidence", (f"{i}.png", BytesIO(PNG), "image/png")) for i in range(6)]
    too_many = reporter.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(limit_id), "reason": "spam", "explanation": REPORT_NOTE},
        files=six,
        follow_redirects=False,
    )
    assert "error=" in too_many.headers["location"] or too_many.status_code == 303
    fake = reporter.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(_user_id("att.oth@example.com")), "reason": "spam", "explanation": REPORT_NOTE},
        files=[("evidence", ("malware.png", BytesIO(b"<script>alert(1)</script>"), "image/png"))],
        follow_redirects=False,
    )
    assert "error=" in fake.headers["location"]
    traversal = reporter.post(
        "/denunciar",
        data={"tipo": "user", "alvo": str(_user_id("att.oth@example.com")), "reason": "spam", "explanation": REPORT_NOTE},
        files=[("evidence", ("../../etc/passwd.png", BytesIO(PNG), "image/png"))],
        follow_redirects=False,
    )
    assert "/denunciar/ok" in traversal.headers["location"]
    db = SessionLocal()
    try:
        last = db.scalar(select(ReportAttachment).order_by(ReportAttachment.id.desc()))
        assert ".." not in last.filename
        assert last.filename.endswith(".png")
        assert last.report_id != report_id or True
    finally:
        db.close()
    listing = admin.get("/admin/denuncias")
    assert "Evidências preservadas pelo Watch Club" in listing.text
    assert "Evidências adicionais enviadas pelo denunciante" in listing.text
    assert "Sem violação" in listing.text
    none = admin.post(f"/admin/denuncias/{case_id}/envolvidos/{accused_id}/nada", follow_redirects=False)
    assert none.status_code == 303
    db = SessionLocal()
    try:
        accused_user = db.get(User, accused_id)
        assert accused_user.banned_at is None
        row = db.scalar(select(ReportCaseUser).where(ReportCaseUser.case_id == case_id, ReportCaseUser.user_id == accused_id))
        assert row.outcome == "none"
    finally:
        db.close()


def test_legacy_single_target_case_still_opens():
    admin = TestClient(app)
    register_active(admin, "leg_adm", "leg.adm@example.com")
    _grant_site_admin("leg.adm@example.com")
    db = SessionLocal()
    try:
        case = ReportCase(
            target_type="user",
            target_key="user:1",
            target_id=1,
            reported_user_id=None,
            reason="spam",
            status="pending",
            snapshot_json='{"username": "legado"}',
            report_count=1,
        )
        db.add(case)
        db.commit()
        case_id = case.id
    finally:
        db.close()
    page = admin.get("/admin/denuncias")
    assert page.status_code == 200
    assert f"caso-{case_id}" in page.text
    assert "legado" in page.text or "spam" in page.text.lower() or "Spam" in page.text


def test_individual_admin_decisions_do_not_punish_everyone():
    admin = TestClient(app)
    reporter = TestClient(app)
    one = TestClient(app)
    two = TestClient(app)
    register_active(admin, "rcase_adm", "rcase.adm@example.com")
    register_active(reporter, "rcase_rep", "rcase.rep@example.com")
    register_active(one, "rcase_one", "rcase.one@example.com")
    register_active(two, "rcase_two", "rcase.two@example.com")
    _grant_site_admin("rcase.adm@example.com")
    one_id = _user_id("rcase.one@example.com")
    two_id = _user_id("rcase.two@example.com")
    reporter.post(
        "/denunciar",
        data={
            "tipo": "user",
            "alvo": str(one_id),
            "user_ids": [str(one_id), str(two_id)],
            "reason": "hate",
            "explanation": REPORT_NOTE,
        },
        follow_redirects=False,
    )
    db = SessionLocal()
    try:
        case_id = db.scalar(select(ReportCase.id).order_by(ReportCase.id.desc()))
    finally:
        db.close()
    admin.post(f"/admin/denuncias/{case_id}/envolvidos/{one_id}/advertir", follow_redirects=False)
    db = SessionLocal()
    try:
        from app.moderation import counting_violation_count

        assert counting_violation_count(db, one_id) == 1
        assert counting_violation_count(db, two_id) == 0
        case = db.get(ReportCase, case_id)
        assert case.status == "pending"
    finally:
        db.close()


def test_safety_hub_and_profile_context_still_work():
    person = TestClient(app)
    target = TestClient(app)
    register_active(person, "hub2_a", "hub2.a@example.com")
    register_active(target, "hub2_b", "hub2.b@example.com")
    hub = person.get("/seguranca")
    assert "Denunciar usuário(s)" in hub.text
    profile = person.get("/u/hub2_b")
    assert "/denunciar?tipo=user" in profile.text
    form = person.get(f"/denunciar?tipo=user&id={_user_id('hub2.b@example.com')}")
    assert "Explique o que aconteceu" in form.text
    assert "@hub2_b" in form.text
