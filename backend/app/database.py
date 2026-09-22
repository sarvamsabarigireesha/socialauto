from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from .config import database_url_problem, settings

# Refuse to start on a DATABASE_URL that cannot work. Before this, a pasted
# placeholder (e.g. "postgresql://...?sslmode=require") died deep inside
# psycopg2 with `could not translate host name "..."`, or silently fell back to
# an empty local SQLite file - both very confusing in production.
_db_problem = database_url_problem(settings.DATABASE_URL)
if _db_problem:
    raise RuntimeError(
        f"\n{'=' * 70}\nDATABASE_URL is set but cannot work: {_db_problem}\n"
        f"Value: {settings.DATABASE_URL[:60]}{'...' if len(settings.DATABASE_URL) > 60 else ''}\n\n"
        f"Fix: open your Postgres provider's dashboard (Neon -> Connect) and copy\n"
        f"the real connection string, it looks like:\n"
        f"  postgresql://USER:PASSWORD@ep-something-123456.REGION.aws.neon.tech/DBNAME?sslmode=require\n"
        f"Then update the DATABASE_URL environment variable and redeploy.\n"
        f"{'=' * 70}\n")

# FIX: Render free Postgres sleeps -> SSL closed error fix
connect_args = {}
if "render" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL:
    connect_args = {"sslmode": "require", "connect_timeout": 10}

# A request killed mid-transaction (deploy, timeout, crash) leaves its connection
# "idle in transaction", still holding row locks. On Neon that wedged the DB for
# minutes: an ALTER queued behind it and every statement behind the ALTER. This
# session setting makes the server close such a transaction after a minute.
if settings.DATABASE_URL.startswith("postgres"):
    _opts = connect_args.setdefault("options", "")
    if "idle_in_transaction_session_timeout" not in _opts:
        connect_args["options"] = (_opts + " -c idle_in_transaction_session_timeout=60000").strip()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # critical fix for SSL closed
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # A failed flush/commit leaves the session in a "rolled back" state, so
        # every later query on it raises PendingRollbackError instead of the real
        # error. Roll back here so the original exception is what the user sees.
        db.rollback()
        raise
    finally:
        db.close()
