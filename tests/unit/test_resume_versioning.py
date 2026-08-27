from __future__ import annotations

from job_agent.resume.versioning import (
    compute_file_hash,
    compute_profile_hash,
    compute_source_hashes,
)


def test_compute_file_hash_is_deterministic(repo_root):
    path = repo_root / "candidate" / "resume_master.docx"
    assert compute_file_hash(path) == compute_file_hash(path)


def test_compute_file_hash_differs_for_different_content(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"hello")
    b.write_bytes(b"world")
    assert compute_file_hash(a) != compute_file_hash(b)


def test_compute_source_hashes_includes_resume_and_candidate_files(real_config):
    hashes = compute_source_hashes(real_config)
    keys = list(hashes.keys())
    assert any(k.endswith("resume_master.docx") for k in keys)
    assert any(k.endswith("skills.md") for k in keys)
    assert any(k.endswith("experience.md") for k in keys)
    assert any(k.endswith("profile.yaml") for k in keys)
    assert any(k.endswith("preferences.yaml") for k in keys)


def test_compute_source_hashes_is_stable(real_config):
    assert compute_source_hashes(real_config) == compute_source_hashes(real_config)


def test_compute_profile_hash_is_deterministic(real_profile):
    assert compute_profile_hash(real_profile) == compute_profile_hash(real_profile)


def test_compute_profile_hash_ignores_parsed_at(real_profile):
    later = real_profile.model_copy(
        update={"parsed_at": real_profile.parsed_at.replace(year=real_profile.parsed_at.year + 1)}
    )
    assert compute_profile_hash(real_profile) == compute_profile_hash(later)


def test_compute_profile_hash_changes_when_content_changes(real_profile):
    changed = real_profile.model_copy(
        update={
            "identity_name": real_profile.identity_name.model_copy(
                update={"value": "Someone Else"}
            )
        }
    )
    assert compute_profile_hash(real_profile) != compute_profile_hash(changed)
