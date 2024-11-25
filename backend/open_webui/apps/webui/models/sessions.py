from datetime import datetime, timedelta
from typing import Optional, Dict

from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from open_webui.apps.webui.internal.db import Base, get_db
from open_webui.utils.utils import decode_token


class UserSession(Base):
    __tablename__ = "user_sessions"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("user.id"))
    socket_id = Column(String, nullable=True)
    last_active = Column(DateTime, nullable=False)
    token = Column(String, nullable=False)
    current_model = Column(String, nullable=True)
    model_metadata = Column(JSON, nullable=True)


class SessionManager:
    def __init__(self, use_redis: bool = False, redis_url: Optional[str] = None):
        self.use_redis = use_redis
        if use_redis:
            from open_webui.apps.socket.utils import RedisDict
            self._redis_sessions = RedisDict("open-webui:sessions", redis_url)
        
    async def create_session(self, user_id: str, socket_id: str, token: str) -> None:
        # Store in database
        with get_db() as db:
            session = UserSession(
                id=socket_id,
                user_id=user_id,
                socket_id=socket_id,
                last_active=datetime.utcnow(),
                token=token
            )
            db.add(session)
            db.commit()

        # Cache in Redis if enabled
        if self.use_redis:
            self._redis_sessions[socket_id] = {
                "user_id": user_id,
                "last_active": datetime.utcnow().timestamp()
            }

    async def get_session(self, socket_id: str) -> Optional[Dict]:
        if self.use_redis:
            # Try Redis first
            session = self._redis_sessions.get(socket_id)
            if session:
                return session

        # Fallback to database
        with get_db() as db:
            session = db.query(UserSession).filter_by(id=socket_id).first()
            if session:
                return {
                    "user_id": session.user_id,
                    "last_active": session.last_active.timestamp()
                }
        return None

    async def update_session(self, socket_id: str) -> None:
        now = datetime.utcnow()
        
        # Update database
        with get_db() as db:
            session = db.query(UserSession).filter_by(id=socket_id).first()
            if session:
                session.last_active = now
                db.commit()

        # Update Redis if enabled
        if self.use_redis:
            session = self._redis_sessions.get(socket_id)
            if session:
                session["last_active"] = now.timestamp()
                self._redis_sessions[socket_id] = session

    async def remove_session(self, socket_id: str) -> None:
        # Remove from database
        with get_db() as db:
            db.query(UserSession).filter_by(id=socket_id).delete()
            db.commit()

        # Remove from Redis if enabled
        if self.use_redis:
            if socket_id in self._redis_sessions:
                del self._redis_sessions[socket_id]

    async def cleanup_expired_sessions(self, expiry_minutes: int = 60) -> None:
        """Remove sessions that haven't been active for the specified duration"""
        expiry_time = datetime.utcnow() - timedelta(minutes=expiry_minutes)
        
        # Cleanup database
        with get_db() as db:
            db.query(UserSession).filter(UserSession.last_active < expiry_time).delete()
            db.commit()

        # Cleanup Redis if enabled
        if self.use_redis:
            current_time = datetime.utcnow().timestamp()
            expired_sids = [
                sid for sid, data in self._redis_sessions.items()
                if current_time - data["last_active"] > expiry_minutes * 60
            ]
            for sid in expired_sids:
                del self._redis_sessions[sid]

    async def update_user_model(self, socket_id: str, model_id: str, metadata: Optional[Dict] = None) -> None:
        """Update the model being used by a session"""
        with get_db() as db:
            session = db.query(UserSession).filter_by(id=socket_id).first()
            if session:
                session.current_model = model_id
                session.model_metadata = metadata or {}
                session.last_active = datetime.utcnow()
                db.commit()

        if self.use_redis:
            session = self._redis_sessions.get(socket_id)
            if session:
                session["current_model"] = model_id
                session["model_metadata"] = metadata or {}
                session["last_active"] = datetime.utcnow().timestamp()
                self._redis_sessions[socket_id] = session
 