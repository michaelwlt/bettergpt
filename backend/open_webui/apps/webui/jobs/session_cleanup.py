import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from open_webui.apps.webui.internal.db import get_db
from open_webui.apps.webui.models.sessions import UserSession
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["JOBS"])

class SessionCleanupJob:
    def __init__(self, interval_minutes: int = 5):
        self.scheduler = AsyncIOScheduler()
        self.interval_minutes = interval_minutes

    async def cleanup_expired_sessions(self):
        """Remove sessions that have been inactive beyond the timeout period"""
        try:
            expiry_time = datetime.utcnow() - timedelta(minutes=self.interval_minutes)
            
            with get_db() as db:
                # Get expired sessions for logging
                expired = db.query(UserSession).filter(
                    UserSession.last_active < expiry_time
                ).all()
                
                # Delete expired sessions
                count = db.query(UserSession).filter(
                    UserSession.last_active < expiry_time
                ).delete()
                
                db.commit()
                
                if count > 0:
                    log.info(f"Cleaned up {count} expired sessions")
                    for session in expired:
                        log.debug(f"Expired session removed - User: {session.user_id}, Socket: {session.socket_id}")
                
        except Exception as e:
            log.error(f"Error during session cleanup: {e}")

    def start(self):
        """Start the cleanup job scheduler"""
        self.scheduler.add_job(
            self.cleanup_expired_sessions,
            trigger=IntervalTrigger(minutes=self.interval_minutes),
            id='session_cleanup',
            name='Session Cleanup Job',
            replace_existing=True
        )
        self.scheduler.start()
        log.info(f"Session cleanup job scheduled - Interval: {self.interval_minutes} minutes")

    def stop(self):
        """Stop the cleanup job scheduler"""
        self.scheduler.shutdown()
        log.info("Session cleanup job stopped") 