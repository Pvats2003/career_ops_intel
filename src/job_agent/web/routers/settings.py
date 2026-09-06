"""Search preferences (Settings page) — Career OS Phase 15.

Pure storage over `SearchPreferences` (see its docstring in `job_agent.
db.models`): a live-editable overlay, never a replacement for
`config/preferences.yaml`/`config/profile.yaml`. A candidate with no row
yet reads back the model's own neutral defaults (0/24h/90/"daily", empty
lists) — never a guessed value — exactly matching "no overrides set yet".
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from job_agent.db.models import SearchPreferences as SearchPreferencesRow
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.schemas import SUPPORTED_COUNTRIES, SearchPreferencesIn, SearchPreferencesOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _out(row: SearchPreferencesRow | None) -> SearchPreferencesOut:
    if row is None:
        return SearchPreferencesOut(
            target_roles=[], target_countries=[], target_cities=[],
            remote_preference=None, min_salary=None, max_experience_gap_years=None,
            industries=[], companies_priority=[], companies_excluded=[],
            min_match_score=0, search_frequency_hours=24,
            notification_min_score=90, notification_frequency="daily",
        )
    return SearchPreferencesOut(
        target_roles=list(row.target_roles), target_countries=list(row.target_countries),
        target_cities=list(row.target_cities), remote_preference=row.remote_preference,
        min_salary=row.min_salary, max_experience_gap_years=row.max_experience_gap_years,
        industries=list(row.industries), companies_priority=list(row.companies_priority),
        companies_excluded=list(row.companies_excluded), min_match_score=row.min_match_score,
        search_frequency_hours=row.search_frequency_hours,
        notification_min_score=row.notification_min_score,
        notification_frequency=row.notification_frequency,
    )


def _get_row(session, candidate_id: int) -> SearchPreferencesRow | None:
    return session.execute(
        select(SearchPreferencesRow).where(SearchPreferencesRow.candidate_id == candidate_id)
    ).scalar_one_or_none()


@router.get("/search-preferences", response_model=SearchPreferencesOut)
def get_search_preferences(session: SessionDep, candidate: CandidateDep) -> SearchPreferencesOut:
    _, candidate_id = candidate
    return _out(_get_row(session, candidate_id))


@router.put("/search-preferences", response_model=SearchPreferencesOut)
def update_search_preferences(
    payload: SearchPreferencesIn, session: SessionDep, candidate: CandidateDep
) -> SearchPreferencesOut:
    """Merges only the fields the caller actually sent — omitted fields
    keep their current stored value (or the model default, for a
    first-time row), never silently reset to null/zero."""
    _, candidate_id = candidate
    row = _get_row(session, candidate_id)
    if row is None:
        row = SearchPreferencesRow(candidate_id=candidate_id)
        session.add(row)

    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(row, field, value)

    session.commit()
    return _out(row)


@router.get("/supported-countries", response_model=list[str])
def get_supported_countries() -> list[str]:
    return list(SUPPORTED_COUNTRIES)
