from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SiteScan, User
from app.services.auth import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if not creds or creds.scheme.lower() != "bearer":
        return None
    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


def get_owned_scan(
    scan_token: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
    x_scan_token: str | None = Header(None, alias="X-Scan-Token"),
) -> SiteScan:
    scan = db.query(SiteScan).filter(SiteScan.token == scan_token).first()
    if not scan:
        raise HTTPException(404, "Scan not found")
    if scan.user_id is not None:
        if not user or user.id != scan.user_id:
            raise HTTPException(403, "Access denied")
    elif x_scan_token != scan.token:
        raise HTTPException(403, "Access denied")
    return scan
