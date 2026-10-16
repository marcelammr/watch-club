from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

connect_args = (
    {"check_same_thread": False, "timeout": 15} if DATABASE_URL.startswith("sqlite") else {}
)
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def exclusive_write_session(source: Session) -> Session:
    """Open a new Session on a fresh connection that starts with BEGIN IMMEDIATE.

    Request handlers already autobegin DEFERRED on login_required SELECTs.
    BEGIN IMMEDIATE cannot be issued inside that transaction, so writes that
    need a reserved lock use a separate Connection/Session instead of nesting
    BEGIN on the read snapshot. session.commit() commits that connection
    transaction (join_transaction_mode=control_fully).
    """
    bind = source.get_bind()
    conn = bind.connect()
    if bind.dialect.name == "sqlite":

        @event.listens_for(conn, "begin", once=True)
        def _begin_immediate(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    session = Session(
        bind=conn,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="control_fully",
    )
    session.info["exclusive_connection"] = conn
    return session


def close_exclusive_session(session: Session) -> None:
    conn = session.info.pop("exclusive_connection", None)
    session.close()
    if conn is not None:
        conn.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
