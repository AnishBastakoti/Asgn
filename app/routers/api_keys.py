import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Any
from config import settings

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth_deps import require_admin
from app.database import get_db
from app.models.api_key import ApiKey

router = APIRouter(prefix="/api/admin/keys", tags=["API Keys"])


KEY_PREFIX = settings.KEY_PREFIX

@router.post("/generate")
def generate_api_key(
    name:         str,
    owner_email:  str,
    expires_days: int = None,
    db:    Session = Depends(get_db),
    admin: Any = Depends(require_admin)
):
    """Admin only — generate a new API key for a partner."""
    random_part = secrets.token_urlsafe(32)
    raw_key     = f"{KEY_PREFIX}_{random_part}"
    key_hash    = hashlib.sha256(raw_key.encode()).hexdigest()


    expires_at = (
        datetime.utcnow() + timedelta(days=expires_days)
        if expires_days else None
    )

    record = ApiKey(
        key_hash=key_hash,
        name=name,
        owner_email=owner_email,
        expires_at=expires_at
    )
    db.add(record)
    db.commit()

    return {
        "api_key":    raw_key,
        "prefix":     KEY_PREFIX,
        "name":       name,
        "expires_at": expires_at,
        "warning":    "Store this key safely — it cannot be retrieved again"
    }


@router.get("/list")
def list_keys(
    db:    Session = Depends(get_db),
    admin: Any = Depends(require_admin)
):
    """Admin only — list all API keys."""
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [
        {
            "id":          k.id,
            "name":        k.name,
            "owner_email": k.owner_email,
            "is_active":   k.is_active,
            "created_at":  k.created_at,
            "expires_at":  k.expires_at,
        }
        for k in keys
    ]


@router.patch("/{key_id}/revoke")
def revoke_key(
    key_id: int,
    db:     Session = Depends(get_db),
    admin: Any = Depends(require_admin)
):
    """Admin only — revoke an API key immediately."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    key.is_active = False
    db.commit()
    return {"message": f"Key '{key.name}' revoked successfully"}