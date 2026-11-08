from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings
s = settings(); args = {"check_same_thread": False} if s.database_url.startswith("sqlite") else {}
engine = create_engine(s.database_url, connect_args=args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
class Base(DeclarativeBase): pass
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()
