from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_agent.candidate.schema import EvidenceLevel, Fact, SkillFact


def test_fact_unknown_sentinel():
    f = Fact.unknown(source="config/preferences.yaml")
    assert f.value == "UNKNOWN"
    assert f.confidence == 0.0
    assert f.verified is False
    assert f.is_unknown is True


def test_fact_confidence_bounds():
    with pytest.raises(ValidationError):
        Fact(value="x", source="s", confidence=1.5, verified=True)
    with pytest.raises(ValidationError):
        Fact(value="x", source="s", confidence=-0.1, verified=True)


@pytest.mark.parametrize(
    "level", [EvidenceLevel.HAS, EvidenceLevel.DEMONSTRATED, EvidenceLevel.ADJACENT]
)
def test_skillfact_accepts_storable_levels(level):
    sf = SkillFact(
        name="Python", category="technical", evidence_level=level, source="s",
        confidence=1.0, verified=True,
    )
    assert sf.evidence_level == level


@pytest.mark.parametrize("level", [EvidenceLevel.MISSING, EvidenceLevel.UNKNOWN])
def test_skillfact_rejects_match_time_only_levels(level):
    """MISSING/UNKNOWN are match-time classifications, never stored facts."""
    with pytest.raises(ValidationError):
        SkillFact(
            name="Python", category="technical", evidence_level=level, source="s",
            confidence=1.0, verified=True,
        )


def test_skillfact_is_immutable():
    sf = SkillFact(
        name="Python", category="technical", evidence_level=EvidenceLevel.HAS,
        source="s", confidence=1.0, verified=True,
    )
    with pytest.raises(ValidationError):
        sf.name = "Java"
