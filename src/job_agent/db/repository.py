"""Persists a parsed CandidateProfile into the database.

Replace-on-reparse semantics: re-running `job-agent profile parse` deletes
and rewrites the single candidate's facts/skills/experiences/projects from
the current candidate/*.md + config state. This is intentional for a
single-candidate V1 system — the candidate files are the source of truth,
the database is a derived, queryable projection of them, not independent
state. (Job/application history in other tables is never touched here.)

Dashboard performance forensic fix: `save_candidate_profile()` is called on
every web request via `job_agent.web.deps.get_candidate()` (nearly every
API endpoint depends on it), so "replace-on-reparse" used to mean
"delete-and-reinsert every child row on every single page view" — real
write amplification against Postgres for a call that, on a normal read-only
dashboard visit, changes nothing at all. `Candidate.profile_fingerprint`
(sha256 of the profile's semantic content, via `job_agent.resume.
versioning.compute_profile_hash`) lets this function tell "the parsed
profile is byte-for-byte the same as what's already stored" across
separate requests/processes and skip the whole delete/reinsert/commit
cycle in that case — the CLI's `job-agent profile parse` still gets exactly
the same replace-on-reparse behavior whenever the profile has genuinely
changed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.candidate.schema import CandidateProfile, Fact
from job_agent.db.models import Candidate, CandidateFact, Experience, Project, Skill
from job_agent.resume.versioning import compute_profile_hash


def _fact_row(candidate_id: int, fact_type: str, key: str, fact: Fact) -> CandidateFact:
    return CandidateFact(
        candidate_id=candidate_id,
        fact_type=fact_type,
        key=key,
        value=str(fact.value),
        source=fact.source,
        confidence=fact.confidence,
        verified=fact.verified,
        note=fact.note,
    )


def save_candidate_profile(session: Session, profile: CandidateProfile) -> int:
    """Upsert the candidate profile. Returns the candidate id.

    A true no-op (zero writes, zero commit) when `existing.profile_fingerprint`
    already matches this profile's content — see module docstring. A NULL
    fingerprint (pre-migration row, or a row never fingerprinted yet) is
    never treated as a match, so existing candidates always resync exactly
    once after upgrading to this behavior.
    """
    existing = session.execute(
        select(Candidate).where(Candidate.email == profile.contact_email.value)
    ).scalar_one_or_none()

    fingerprint = compute_profile_hash(profile)
    if existing is not None and existing.profile_fingerprint == fingerprint:
        return existing.id

    if existing is None:
        candidate = Candidate(
            name=profile.identity_name.value,
            email=profile.contact_email.value,
            phone=profile.contact_phone.value,
            linkedin=profile.contact_linkedin.value,
            current_location=profile.identity_current_location.value,
            parsed_at=profile.parsed_at,
            source_files=list(profile.source_files),
            profile_fingerprint=fingerprint,
        )
        session.add(candidate)
        session.flush()  # assign candidate.id
    else:
        candidate = existing
        candidate.profile_fingerprint = fingerprint
        candidate.name = profile.identity_name.value
        candidate.phone = profile.contact_phone.value
        candidate.linkedin = profile.contact_linkedin.value
        candidate.current_location = profile.identity_current_location.value
        candidate.parsed_at = profile.parsed_at
        candidate.source_files = list(profile.source_files)
        # Replace derived rows for this candidate.
        for fact_row in list(candidate.facts):
            session.delete(fact_row)
        for skill_row in list(candidate.skills):
            session.delete(skill_row)
        for exp_row in list(candidate.experiences):
            session.delete(exp_row)
        for proj_row in list(candidate.projects):
            session.delete(proj_row)
        session.flush()

    candidate_id = candidate.id

    for skill in profile.skills:
        session.add(
            Skill(
                candidate_id=candidate_id,
                name=skill.name,
                category=skill.category,
                evidence_level=skill.evidence_level.value,
                source=skill.source,
                confidence=skill.confidence,
                verified=skill.verified,
                note=skill.note,
            )
        )

    for exp in profile.experience:
        session.add(
            Experience(
                candidate_id=candidate_id,
                title=exp.title,
                company=exp.company,
                start_date=exp.start_date,
                end_date=exp.end_date,
                domain=exp.domain,
                location=exp.location,
                highlights=list(exp.highlights),
                source=exp.source,
                confidence=exp.confidence,
                verified=exp.verified,
            )
        )

    for proj in profile.projects:
        session.add(
            Project(
                candidate_id=candidate_id,
                name=proj.name,
                status=proj.status,
                project_type=proj.project_type,
                stack=proj.stack,
                highlights=list(proj.highlights),
                source=proj.source,
                confidence=proj.confidence,
                verified=proj.verified,
            )
        )

    for edu in profile.education:
        session.add(
            _fact_row(candidate_id, "education", edu.program, Fact(
                value=f"{edu.institution} ({edu.graduation_date}, {edu.degree_level})",
                source=edu.source,
                confidence=edu.confidence,
                verified=edu.verified,
            ))
        )

    for cert in profile.certifications:
        session.add(
            _fact_row(candidate_id, "certification", cert.name, Fact(
                value=cert.provider or "",
                source=cert.source,
                confidence=cert.confidence,
                verified=cert.verified,
                note=", ".join(cert.covers) if cert.covers else None,
            ))
        )

    for ach in profile.achievements:
        session.add(
            _fact_row(candidate_id, "achievement", ach.title, Fact(
                value="; ".join(ach.highlights),
                source=ach.source,
                confidence=ach.confidence,
                verified=ach.verified,
                note=ach.date,
            ))
        )

    for role_tier, roles in (
        ("target_role_primary", profile.target_roles.primary),
        ("target_role_secondary", profile.target_roles.secondary),
        ("target_role_exploratory", profile.target_roles.exploratory),
    ):
        for role in roles:
            session.add(
                _fact_row(candidate_id, role_tier, role, Fact(
                    value=role, source="config/profile.yaml", confidence=1.0, verified=True
                ))
            )

    preference_facts: list[tuple[str, str, Fact]] = [
        ("work_preference", "remote", profile.work_preferences.remote),
        ("work_preference", "willing_to_relocate", profile.work_preferences.willing_to_relocate),
        ("work_preference", "notice_period", profile.work_preferences.notice_period),
        (
            "location_preference",
            "open_to_countries",
            profile.location_preferences.open_to_countries,
        ),
        ("salary_preference", "currency", profile.salary_preferences.currency),
        ("salary_preference", "minimum_annual", profile.salary_preferences.minimum_annual),
        ("salary_preference", "target_annual", profile.salary_preferences.target_annual),
        ("visa_information", "nationality", profile.visa_information.nationality),
        (
            "visa_information",
            "requires_sponsorship_us",
            profile.visa_information.requires_sponsorship_us,
        ),
        (
            "visa_information",
            "requires_sponsorship_uk",
            profile.visa_information.requires_sponsorship_uk,
        ),
        (
            "visa_information",
            "requires_sponsorship_eu",
            profile.visa_information.requires_sponsorship_eu,
        ),
    ]
    for fact_type, key, fact in preference_facts:
        session.add(_fact_row(candidate_id, fact_type, key, fact))

    session.commit()
    return candidate_id
