"""Ops endpoints: health, identity, packs, stats and audit-chain verification."""
from fastapi import APIRouter, Depends

from app.auth import User, admin, get_current_user, staff
from app.paths import ApiPath
from app.services.container import Services, services

router = APIRouter(tags=["Ops"])


@router.get(ApiPath.HEALTH)
def health():
    return {"status": "ok", "service": "api"}


@router.get(ApiPath.ME)
def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "roles": sorted(user.roles)}


@router.get(ApiPath.PACKS)
def packs(_: User = Depends(staff), s: Services = Depends(services)):
    return s.packs


@router.get(ApiPath.STATS)
def stats(includeSimulated: bool = False, _: User = Depends(staff), s: Services = Depends(services)):
    return s.dashboard.stats(includeSimulated)


@router.get(ApiPath.AUDIT_VERIFY)
def verify_audit(_: User = Depends(admin), s: Services = Depends(services)):
    return s.audit.verify_all()
