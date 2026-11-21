from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db, get_settings
from app.schemas.pairing import PairingClaim, PairingClaimed
from app.services import pairing

# The only unauthenticated route that hands out a credential. It is guarded by a single-use,
# short-lived code and a per-address rate limit; the response is never cached.
router = APIRouter(prefix="/api/v1/pairing", tags=["device pairing"])


@router.post("/claim", response_model=PairingClaimed)
def claim(
    payload: PairingClaim,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PairingClaimed:
    request.app.state.pairing_limiter.check(request.client.host if request.client else "unknown")
    return pairing.claim(db, payload.code, settings)
