# TODO: move socket to webui app

import asyncio
import logging
from typing import Dict

import socketio
from fastapi import FastAPI

from open_webui.apps.webui.internal.db import get_db
from open_webui.apps.webui.models.sessions import SessionManager, UserSession
from open_webui.apps.webui.models.users import Users
from open_webui.apps.webui.jobs.session_cleanup import SessionCleanupJob
from open_webui.env import (
    SRC_LOG_LEVELS,
    WEBSOCKET_MANAGER,
    WEBSOCKET_REDIS_URL,
)
from open_webui.utils.utils import decode_token

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["SOCKET"])

# Initialize Socket.IO server
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[],
    logger=False,
    engineio_logger=False,
)

# Initialize FastAPI app
app = FastAPI()
socket_app = socketio.ASGIApp(sio)

# Initialize managers
session_manager = SessionManager(
    use_redis=WEBSOCKET_MANAGER == "redis",
    redis_url=WEBSOCKET_REDIS_URL
)

cleanup_job = SessionCleanupJob(interval_minutes=5)

############################
# Socket Event Handlers
############################

@sio.event
async def connect(sid, environ, auth):
    """Handle new socket connections"""
    try:
        if not auth or "token" not in auth:
            log.warning(f"Connection rejected - missing token: {sid}")
            await sio.disconnect(sid)
            return

        data = decode_token(auth["token"])
        if not data or "id" not in data:
            log.warning(f"Connection rejected - invalid token: {sid}")
            await sio.disconnect(sid)
            return

        user = Users.get_user_by_id(data["id"])
        if not user:
            log.warning(f"Connection rejected - user not found: {sid}")
            await sio.disconnect(sid)
            return

        # Create new session
        await session_manager.create_session(
            user_id=user.id,
            socket_id=sid,
            token=auth["token"]
        )
        
        log.info(f"New connection established: {sid} (User: {user.id})")
        
        # Emit detailed statistics
        await sio.emit("user-count", await get_active_user_count())
        await sio.emit("usage", {"models": await get_models_in_use()})

    except Exception as e:
        log.error(f"Error in connect handler: {e}")
        await sio.disconnect(sid)

@sio.event
async def disconnect(sid):
    """Handle socket disconnections"""
    try:
        await session_manager.remove_session(sid)
        log.info(f"Connection closed: {sid}")
        
        # Emit updated statistics
        await sio.emit("user-count", await get_active_user_count())
        await sio.emit("usage", {"models": await get_models_in_use()})
    except Exception as e:
        log.error(f"Error in disconnect handler: {e}")

@sio.event
async def ping(sid):
    """Handle ping events to keep connection alive"""
    try:
        await session_manager.update_session(sid)
    except Exception as e:
        log.error(f"Error in ping handler: {e}")
        await sio.disconnect(sid)

@sio.event
async def model_start(sid, model_id, metadata=None):
    """Handle when a user starts using a model"""
    try:
        await session_manager.update_user_model(sid, model_id, metadata)
        await sio.emit("usage", {"models": await get_models_in_use()})
    except Exception as e:
        log.error(f"Error in model_start handler: {e}")

@sio.event
async def model_stop(sid):
    """Handle when a user stops using a model"""
    try:
        await session_manager.update_user_model(sid, None, None)
        await sio.emit("usage", {"models": await get_models_in_use()})
    except Exception as e:
        log.error(f"Error in model_stop handler: {e}")

############################
# Helper Functions
############################

async def get_active_user_count() -> Dict[str, int]:
    """Get detailed user activity statistics"""
    try:
        with get_db() as db:
            # Get total unique active users
            total_users = db.query(UserSession.user_id)\
                .distinct()\
                .count()
            
            # Get users currently using models
            active_users = db.query(UserSession.user_id)\
                .filter(UserSession.current_model.isnot(None))\
                .distinct()\
                .count()
            
            return {
                "total": total_users,
                "active": active_users
            }
    except Exception as e:
        log.error(f"Error getting user count: {e}")
        return {"total": 0, "active": 0}

async def get_models_in_use() -> Dict[str, Dict]:
    """Get detailed model usage statistics"""
    try:
        with get_db() as db:
            # Query active sessions using models
            sessions = db.query(UserSession)\
                .filter(UserSession.current_model.isnot(None))\
                .all()
            
            model_usage = {}
            for session in sessions:
                model_id = session.current_model
                if model_id:
                    if model_id not in model_usage:
                        model_usage[model_id] = {
                            "count": 0,
                            "users": set(),
                            "sessions": []
                        }
                    
                    model_usage[model_id]["count"] += 1
                    model_usage[model_id]["users"].add(session.user_id)
                    model_usage[model_id]["sessions"].append({
                        "socket_id": session.socket_id,
                        "user_id": session.user_id,
                        "metadata": session.model_metadata,
                        "last_active": session.last_active.isoformat()
                    })
            
            # Convert sets to lists for JSON serialization
            for model in model_usage.values():
                model["users"] = list(model["users"])
                model["unique_users"] = len(model["users"])
            
            return model_usage
    except Exception as e:
        log.error(f"Error getting model usage: {e}")
        return {}

# Update FastAPI startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Start the cleanup job on application startup"""
    cleanup_job.start()
    log.info("Socket application started - Cleanup job initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop the cleanup job on application shutdown"""
    cleanup_job.stop()
    log.info("Socket application shutting down - Cleanup job stopped")
