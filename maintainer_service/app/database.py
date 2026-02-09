"""Database management for issue state tracking."""

from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

Base = declarative_base()


class ProcessedIssue(Base):
    """Tracks issues that have been analyzed and reported."""
    
    __tablename__ = "processed_issues"
    
    issue_id = Column(String, primary_key=True)
    novelty_score = Column(Integer, nullable=True)
    is_duplicate = Column(Boolean, default=False)
    last_analyzed_at = Column(DateTime, default=datetime.utcnow)
    reported_in_digest = Column(Boolean, default=False)
    short_summary = Column(String, nullable=True)


# Create directory if it doesn't exist
from pathlib import Path
db_path = Path(settings.sqlite_db_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

# Create engine and session
engine = create_engine(f"sqlite:///{settings.sqlite_db_path}")
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Initialize the database schema."""
    Base.metadata.create_all(engine)


def get_session():
    """Get a database session."""
    return SessionLocal()
