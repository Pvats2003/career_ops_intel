"""Job match output schema — BUILD PROMPT section 10.

`JobMatchResult` is the persisted, explainable record of one matching run:
every sub-score, why it was computed, and what (if anything) forced the
decision regardless of score. `hard_stop_reasons`/`excluded_reasons` are
kept separate from `concerns` deliberately — `concerns` are informational
(surfaced to a human reviewer), while the other two are the only things
that can override a numeric score, and callers must be able to tell which
happened.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Decision(StrEnum):
    APPLY = "APPLY"
    REVIEW = "REVIEW"
    SAVE = "SAVE"
    SKIP = "SKIP"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class JobMatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall_score: int = Field(ge=0, le=100)
    decision: Decision

    skills_match: int = Field(ge=0, le=100)
    experience_match: int = Field(ge=0, le=100)
    role_match: int = Field(ge=0, le=100)
    project_match: int = Field(ge=0, le=100)
    education_match: int = Field(ge=0, le=100)
    location_match: int = Field(ge=0, le=100)
    seniority_match: int = Field(ge=0, le=100)
    eligibility_match: int = Field(ge=0, le=100)

    missing_requirements: tuple[str, ...] = Field(default_factory=tuple)
    concerns: tuple[str, ...] = Field(default_factory=tuple)
    reasoning: str

    # What (if anything) forced the decision regardless of overall_score.
    hard_stop_reasons: tuple[str, ...] = Field(default_factory=tuple)
    excluded_reasons: tuple[str, ...] = Field(default_factory=tuple)

    # Matching Engine V2 (audit item G — "numeric score must agree with
    # decision"). `raw_fit_score` is the uncapped weighted-average score
    # exactly as before; `overall_score` above is the FINAL, capped score
    # actually used for the decision and shown as the headline number.
    # Never hides the raw evidence — both are kept, always. A strong
    # negative signal (`risk_flags`, e.g. an incompatible role family)
    # caps `overall_score` without forcing HUMAN_REQUIRED the way a real
    # hard stop does; see job_agent.matching.scoring._apply_score_caps.
    raw_fit_score: int = Field(ge=0, le=100, default=0)
    risk_flags: tuple[str, ...] = Field(default_factory=tuple)

    semantic_available: bool
    prompt_version: str | None = None
    model_used: str | None = None
