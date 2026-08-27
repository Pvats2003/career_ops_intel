"""Parses candidate/*.md into a validated CandidateProfile.

This is a deterministic parser, not an LLM call — the candidate knowledge
base files use a fixed, documented structure (see the comment at the top of
each candidate/*.md file) specifically so that ingestion does not need to
guess. Every produced Fact/SkillFact/entry carries `source` pointing back at
the exact file it came from, satisfying BUILD PROMPT section 3's provenance
requirement.

Preference-shaped fields (work/location/salary/visa, target roles) are not
in candidate/*.md at all — they come from config/preferences.yaml and
config/profile.yaml, which the human edits directly. A value of the literal
string "UNKNOWN" in those files becomes an unverified `Fact.unknown(...)`
here; it is never inferred from other data.
"""

from __future__ import annotations

from pathlib import Path

from job_agent.candidate.schema import (
    AchievementEntry,
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    EvidenceLevel,
    ExperienceEntry,
    Fact,
    LocationPreferences,
    ProjectEntry,
    SalaryPreferences,
    SkillFact,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.config.loader import REPO_ROOT, AppConfig


class CandidateParseError(ValueError):
    """Raised when a candidate/*.md file does not match the expected format."""


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise CandidateParseError(f"Missing required candidate file: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def _kv_line(line: str) -> tuple[str, str] | None:
    if ":" not in line or line.strip().startswith(("#", "-")):
        return None
    key, _, val = line.partition(":")
    if not key or key != key.strip():
        return None
    return key.strip().lower(), val.strip()


def _iter_blocks(lines: list[str], header_prefix: str) -> list[tuple[str, list[str]]]:
    """Split lines into (header_text, body_lines) blocks at `header_prefix`."""
    blocks: list[tuple[str, list[str]]] = []
    header: str | None = None
    body: list[str] = []
    for line in lines:
        if line.startswith(header_prefix) and not line.startswith(header_prefix + "#"):
            if header is not None:
                blocks.append((header, body))
            header = line[len(header_prefix) :].strip()
            body = []
        else:
            body.append(line)
    if header is not None:
        blocks.append((header, body))
    return blocks


def _parse_metadata_and_bullets(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """Metadata `key: value` lines followed by `- bullet` lines (with wrapped
    continuation lines indented by leading whitespace)."""
    metadata: dict[str, str] = {}
    bullets: list[str] = []
    for raw in lines:
        if not raw.strip():
            continue
        if raw.startswith("- "):
            bullets.append(raw[2:].strip())
            continue
        if raw.startswith((" ", "\t")) and bullets:
            bullets[-1] = f"{bullets[-1]} {raw.strip()}"
            continue
        kv = _kv_line(raw)
        if kv is not None and not bullets:
            metadata[kv[0]] = kv[1]
    return metadata, bullets


def _parse_kv_bullets(lines: list[str]) -> list[dict[str, str]]:
    """Bullets whose own body is itself `key: value` pairs, e.g.:
    - name: Google UX Design Certificate
      provider: Coursera
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in lines:
        if not raw.strip():
            continue
        if raw.startswith("- "):
            if current is not None:
                entries.append(current)
            current = {}
            kv = _kv_line(raw[2:].strip())
            if kv:
                current[kv[0]] = kv[1]
            continue
        if raw.startswith((" ", "\t")) and current is not None:
            kv = _kv_line(raw.strip())
            if kv:
                current[kv[0]] = kv[1]
    if current is not None:
        entries.append(current)
    return entries


# --------------------------------------------------------------------------
# profile.md
# --------------------------------------------------------------------------
def parse_profile(path: Path) -> dict[str, str]:
    lines = _read_lines(path)
    sections = dict(_iter_blocks(lines, "## "))
    result: dict[str, str] = {}
    for section_name in ("Identity", "Contact"):
        body = sections.get(section_name)
        if body is None:
            raise CandidateParseError(f"{path}: missing required '## {section_name}' section")
        for raw in body:
            kv = _kv_line(raw)
            if kv:
                result[kv[0]] = kv[1]
    for required in ("name", "current_location", "email", "phone", "linkedin"):
        if required not in result:
            raise CandidateParseError(f"{path}: missing required field '{required}'")
    return result


# --------------------------------------------------------------------------
# experience.md
# --------------------------------------------------------------------------
def parse_experience(path: Path) -> list[ExperienceEntry]:
    lines = _read_lines(path)
    source = _rel(path)
    entries: list[ExperienceEntry] = []
    for header, body in _iter_blocks(lines, "### "):
        if "|" not in header:
            raise CandidateParseError(
                f"{path}: experience header '{header}' must be 'Title | Company'"
            )
        title, _, company = header.partition("|")
        metadata, bullets = _parse_metadata_and_bullets(body)
        for required in ("start_date", "end_date"):
            if required not in metadata:
                raise CandidateParseError(
                    f"{path}: experience '{header}' missing '{required}'"
                )
        entries.append(
            ExperienceEntry(
                title=title.strip(),
                company=company.strip(),
                start_date=metadata["start_date"],
                end_date=metadata["end_date"],
                domain=metadata.get("domain"),
                location=metadata.get("location"),
                highlights=tuple(bullets),
                source=source,
            )
        )
    return entries


# --------------------------------------------------------------------------
# projects.md
# --------------------------------------------------------------------------
def parse_projects(path: Path) -> list[ProjectEntry]:
    lines = _read_lines(path)
    source = _rel(path)
    entries: list[ProjectEntry] = []
    for header, body in _iter_blocks(lines, "### "):
        metadata, bullets = _parse_metadata_and_bullets(body)
        for required in ("status", "type"):
            if required not in metadata:
                raise CandidateParseError(f"{path}: project '{header}' missing '{required}'")
        entries.append(
            ProjectEntry(
                name=header.strip(),
                status=metadata["status"],
                project_type=metadata["type"],
                stack=metadata.get("stack"),
                highlights=tuple(bullets),
                source=source,
            )
        )
    return entries


# --------------------------------------------------------------------------
# skills.md
# --------------------------------------------------------------------------
def parse_skills(path: Path) -> list[SkillFact]:
    lines = _read_lines(path)
    source = _rel(path)
    skills: list[SkillFact] = []
    for _header, body in _iter_blocks(lines, "## "):
        for raw in body:
            if not raw.startswith("- "):
                continue
            parts = [p.strip() for p in raw[2:].split("::")]
            if len(parts) < 3:
                raise CandidateParseError(
                    f"{path}: skill line '{raw}' must be "
                    "'Name :: category :: EVIDENCE_LEVEL [:: note]'"
                )
            name, category, level_str, *rest = parts
            try:
                level = EvidenceLevel(level_str.upper())
            except ValueError as exc:
                raise CandidateParseError(
                    f"{path}: unknown evidence level '{level_str}' for skill '{name}'"
                ) from exc
            skills.append(
                SkillFact(
                    name=name,
                    category=category,
                    evidence_level=level,
                    source=source,
                    confidence=1.0,
                    verified=True,
                    note=" :: ".join(rest) if rest else None,
                )
            )
    return skills


# --------------------------------------------------------------------------
# education.md
# --------------------------------------------------------------------------
def parse_education(path: Path) -> tuple[list[EducationEntry], list[CertificationEntry]]:
    lines = _read_lines(path)
    source = _rel(path)
    education: list[EducationEntry] = []
    certifications: list[CertificationEntry] = []

    for header, body in _iter_blocks(lines, "### "):
        metadata, _bullets = _parse_metadata_and_bullets(body)
        for required in ("institution", "graduation_date", "degree_level"):
            if required not in metadata:
                raise CandidateParseError(f"{path}: education '{header}' missing '{required}'")
        education.append(
            EducationEntry(
                program=header.strip(),
                institution=metadata["institution"],
                graduation_date=metadata["graduation_date"],
                degree_level=metadata["degree_level"],
                source=source,
            )
        )

    for header, body in _iter_blocks(lines, "## "):
        if header.strip().lower() != "certifications":
            continue
        for entry in _parse_kv_bullets(body):
            if "name" not in entry:
                raise CandidateParseError(f"{path}: certification entry missing 'name'")
            covers_raw = entry.get("covers", "")
            covers = tuple(c.strip() for c in covers_raw.split(",") if c.strip())
            certifications.append(
                CertificationEntry(
                    name=entry["name"],
                    provider=entry.get("provider"),
                    covers=covers,
                    source=source,
                )
            )
    return education, certifications


# --------------------------------------------------------------------------
# achievements.md
# --------------------------------------------------------------------------
def parse_achievements(path: Path) -> list[AchievementEntry]:
    lines = _read_lines(path)
    source = _rel(path)
    achievements: list[AchievementEntry] = []

    for header, body in _iter_blocks(lines, "### "):
        metadata, bullets = _parse_metadata_and_bullets(body)
        achievements.append(
            AchievementEntry(
                title=header.strip(),
                date=metadata.get("date"),
                highlights=tuple(bullets),
                source=source,
            )
        )

    for header, body in _iter_blocks(lines, "## "):
        if "metric" not in header.strip().lower():
            continue
        for entry in _parse_kv_bullets(body):
            if "metric" not in entry:
                continue
            title = entry.get("source", header.strip())
            achievements.append(
                AchievementEntry(
                    title=title,
                    date=None,
                    highlights=(entry["metric"].strip('"'),),
                    source=source,
                )
            )
    return achievements


# --------------------------------------------------------------------------
# Preference-shaped fields, sourced from config, not candidate/*.md
# --------------------------------------------------------------------------
def _pref_fact(value: str, *, source: str) -> Fact[str]:
    if value.strip().upper() == "UNKNOWN":
        return Fact.unknown(source=source)
    return Fact(value=value, source=source, confidence=1.0, verified=True)


# --------------------------------------------------------------------------
# Top-level assembly
# --------------------------------------------------------------------------
def parse_candidate_profile(
    config: AppConfig,
    candidate_dir: Path | None = None,
) -> CandidateProfile:
    """Build the full CandidateProfile from candidate/*.md + config/*.yaml."""
    cdir = candidate_dir or config.env.candidate_dir

    profile_fields = parse_profile(cdir / "profile.md")
    profile_source = _rel(cdir / "profile.md")
    experience = parse_experience(cdir / "experience.md")
    projects = parse_projects(cdir / "projects.md")
    skills = parse_skills(cdir / "skills.md")
    education, certifications = parse_education(cdir / "education.md")
    achievements = parse_achievements(cdir / "achievements.md")

    prefs = config.preferences
    profile_cfg = config.profile

    work_preferences = WorkPreferences(
        remote=_pref_fact(prefs.work_preferences.remote, source="config/preferences.yaml"),
        employment_types=tuple(prefs.work_preferences.employment_types),
        willing_to_relocate=_pref_fact(
            prefs.work_preferences.willing_to_relocate, source="config/preferences.yaml"
        ),
        notice_period=_pref_fact(
            prefs.work_preferences.notice_period, source="config/preferences.yaml"
        ),
    )
    location_preferences = LocationPreferences(
        current_location=_pref_fact(
            prefs.location_preferences.current_location, source="config/preferences.yaml"
        ),
        preferred_locations=tuple(prefs.location_preferences.preferred_locations),
        open_to_countries=_pref_fact(
            prefs.location_preferences.open_to_countries, source="config/preferences.yaml"
        ),
    )
    salary_preferences = SalaryPreferences(
        currency=_pref_fact(prefs.salary_preferences.currency, source="config/preferences.yaml"),
        minimum_annual=_pref_fact(
            prefs.salary_preferences.minimum_annual, source="config/preferences.yaml"
        ),
        target_annual=_pref_fact(
            prefs.salary_preferences.target_annual, source="config/preferences.yaml"
        ),
        negotiable=_pref_fact(
            prefs.salary_preferences.negotiable, source="config/preferences.yaml"
        ),
    )
    visa_information = VisaInformation(
        nationality=_pref_fact(
            prefs.visa_information.nationality, source="config/preferences.yaml"
        ),
        requires_sponsorship_us=_pref_fact(
            prefs.visa_information.requires_sponsorship_us, source="config/preferences.yaml"
        ),
        requires_sponsorship_uk=_pref_fact(
            prefs.visa_information.requires_sponsorship_uk, source="config/preferences.yaml"
        ),
        requires_sponsorship_eu=_pref_fact(
            prefs.visa_information.requires_sponsorship_eu, source="config/preferences.yaml"
        ),
        requires_sponsorship_other=_pref_fact(
            prefs.visa_information.requires_sponsorship_other, source="config/preferences.yaml"
        ),
        currently_authorized_countries=tuple(
            prefs.visa_information.currently_authorized_countries
        ),
    )

    return CandidateProfile(
        identity_name=Fact(
            value=profile_fields["name"], source=profile_source, confidence=1.0, verified=True
        ),
        identity_current_location=Fact(
            value=profile_fields["current_location"],
            source=profile_source,
            confidence=1.0,
            verified=True,
        ),
        contact_email=Fact(
            value=profile_fields["email"], source=profile_source, confidence=1.0, verified=True
        ),
        contact_phone=Fact(
            value=profile_fields["phone"], source=profile_source, confidence=1.0, verified=True
        ),
        contact_linkedin=Fact(
            value=profile_fields["linkedin"],
            source=profile_source,
            confidence=1.0,
            verified=True,
        ),
        education=tuple(education),
        certifications=tuple(certifications),
        experience=tuple(experience),
        projects=tuple(projects),
        achievements=tuple(achievements),
        skills=tuple(skills),
        languages=(),
        target_roles=TargetRoles(
            primary=tuple(profile_cfg.target_roles.primary),
            secondary=tuple(profile_cfg.target_roles.secondary),
            exploratory=tuple(profile_cfg.target_roles.exploratory),
        ),
        target_industries=tuple(profile_cfg.target_industries),
        excluded_roles=tuple(profile_cfg.excluded_roles),
        excluded_companies=tuple(profile_cfg.excluded_companies),
        work_preferences=work_preferences,
        location_preferences=location_preferences,
        salary_preferences=salary_preferences,
        visa_information=visa_information,
        source_files=tuple(
            _rel(cdir / name)
            for name in (
                "profile.md",
                "experience.md",
                "projects.md",
                "skills.md",
                "education.md",
                "achievements.md",
            )
        ),
    )
