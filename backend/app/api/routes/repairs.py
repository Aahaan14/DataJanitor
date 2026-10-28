"""
DataJanitor — repair plan routes (Phase 4 workflow, Phase 5 persistence).

  GET  /api/datasets/{id}/suggested-rules          starter validation rules
  POST /api/datasets/{id}/repair-plan              scan + validate + propose
  GET  /api/repair-plans/{plan_id}                 plan summary
  GET  /api/repair-plans/{plan_id}/proposals       filtered, paged proposals
  POST /api/repair-plans/{plan_id}/proposals/{proposal_id}/decision
  POST /api/repair-plans/{plan_id}/approve-safe    bulk-approve safe proposals
  GET  /api/repair-plans/{plan_id}/approved        approved repairs (for Phase 6)

No route here modifies the dataset or the stored upload.
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.base import get_db
from app.schemas.dataset import ErrorResponse
from app.schemas.issues import IssueType
from app.schemas.repairs import (
    ApprovedRepairsResponse, ApproveSafeResponse, Classification, CreatePlanRequest,
    DecisionRequest, PlanSummary, ProposalPage, ProposalStatus, RepairProposal,
    SuggestedRulesResponse,
)
from app.schemas.validation import RuleSet
from app.services import (
    dataset_service, decision_service, email_service, plan_service, validation_service,
)

router = APIRouter(tags=["Repairs"])

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Unknown dataset, plan or proposal"},
    409: {"model": ErrorResponse, "description": "Plan stale/superseded or proposals conflict"},
    410: {"model": ErrorResponse, "description": "Dataset deleted or expired"},
    422: {"model": ErrorResponse, "description": "Invalid value or request"},
}


@router.get("/api/datasets/{dataset_id}/suggested-rules", response_model=SuggestedRulesResponse,
            responses=_ERRORS, summary="Starter validation rules inferred from the data")
def suggested_rules(dataset_id: str, settings: Settings = Depends(get_settings),
                    db: Session = Depends(get_db)):
    _, _, df = dataset_service.load_frame(db, settings, dataset_id)
    return SuggestedRulesResponse(dataset_id=dataset_id, rules=validation_service.suggest_rules(df))


@router.post("/api/datasets/{dataset_id}/repair-plan", response_model=PlanSummary,
             status_code=201, responses=_ERRORS,
             summary="Generate reviewable repair proposals (changes nothing)")
def create_repair_plan(dataset_id: str, request: Request, background: BackgroundTasks,
                       body: Optional[CreatePlanRequest] = None,
                       settings: Settings = Depends(get_settings),
                       db: Session = Depends(get_db)) -> PlanSummary:
    rules = body.rules if body and body.rules else RuleSet()
    summary = plan_service.create_plan(db, settings, dataset_id, rules)
    email_service.queue_report(background, request.app.state.session_factory, settings,
                               "scan", summary.scan_id)  # the plan's scan was a completed scan
    return summary


@router.get("/api/repair-plans/{plan_id}", response_model=PlanSummary, responses=_ERRORS,
            summary="Plan summary (also re-checks whether the plan has gone stale)")
def get_plan(plan_id: str, settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> PlanSummary:
    plan = plan_service.get_plan(db, plan_id)
    decision_service.refresh_status(db, settings.upload_path, plan)
    return plan_service.plan_summary(db, plan)


@router.get("/api/repair-plans/{plan_id}/proposals", response_model=ProposalPage,
            responses=_ERRORS, summary="List proposals (filter and page)")
def list_proposals(
    plan_id: str,
    status: Optional[ProposalStatus] = None,
    classification: Optional[Classification] = None,
    issue_type: Optional[IssueType] = None,
    column: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ProposalPage:
    plan = plan_service.get_plan(db, plan_id)
    decision_service.refresh_status(db, settings.upload_path, plan)
    return plan_service.proposal_page(
        db, plan, offset=offset, limit=limit,
        status=status.value if status else None,
        classification=classification.value if classification else None,
        issue_type=issue_type.value if issue_type else None, column=column)


@router.post("/api/repair-plans/{plan_id}/proposals/{proposal_id}/decision",
             response_model=RepairProposal, responses=_ERRORS,
             summary="Approve or reject one proposal")
def decide_proposal(plan_id: str, proposal_id: str, body: DecisionRequest,
                    settings: Settings = Depends(get_settings),
                    db: Session = Depends(get_db)) -> RepairProposal:
    plan = plan_service.get_plan(db, plan_id)
    row = decision_service.decide(db, settings.upload_path, plan, proposal_id,
                                  body.decision, body.chosen_value)
    return plan_service.to_schema(row)


@router.post("/api/repair-plans/{plan_id}/approve-safe", response_model=ApproveSafeResponse,
             responses=_ERRORS, summary="Approve all pending SAFE proposals without conflicts")
def approve_safe(plan_id: str, settings: Settings = Depends(get_settings),
                 db: Session = Depends(get_db)):
    plan = plan_service.get_plan(db, plan_id)
    return decision_service.approve_all_safe(db, settings.upload_path, plan)


@router.get("/api/repair-plans/{plan_id}/approved", response_model=ApprovedRepairsResponse,
            responses=_ERRORS, summary="Explicitly approved repairs (input for Phase 6)")
def approved(plan_id: str, settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)):
    plan = plan_service.get_plan(db, plan_id)
    return decision_service.approved_repairs(db, settings.upload_path, plan)
