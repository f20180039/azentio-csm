"""Wires storage, clock, playbook and services together for one app instance."""
from dataclasses import dataclass

from fastapi import Request

from app.audit import AuditLog
from app.clock import Clock
from app.config import Settings
from app.db import Database
from app.playbook import load_playbook
from app.services.cases import CaseService
from app.services.dashboard import DashboardService
from app.services.packs import load_packs
from app.services.renewals import RenewalService
from app.services.support import SupportService


@dataclass
class Services:
    settings: Settings
    clock: Clock
    db: Database
    audit: AuditLog
    renewals: RenewalService
    support: SupportService
    dashboard: DashboardService
    cases: CaseService
    packs: list[dict]


def build(settings: Settings, clock: Clock | None = None) -> Services:
    clock = clock or Clock()
    db = Database(settings.db_path)
    audit = AuditLog(db, clock)
    playbook = load_playbook(settings.playbook_path)
    return Services(
        settings=settings, clock=clock, db=db, audit=audit,
        renewals=RenewalService(db, audit, playbook, clock, settings.enforce_calling_hours),
        support=SupportService(db, audit, clock),
        dashboard=DashboardService(db, audit, clock),
        cases=CaseService(db, audit, clock),
        packs=load_packs(),
    )


def services(request: Request) -> Services:
    return request.app.state.services
