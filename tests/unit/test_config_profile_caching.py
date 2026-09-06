"""Dashboard performance forensic fix — `web/deps.py:get_config()`/
`get_candidate()` call `load_config()`/`parse_candidate_profile()` fresh on
every single web request by design (so editing config/candidate files on
disk takes effect on the next request, and tests can monkeypatch env vars
per-test). That correctly meant re-reading + re-validating/re-parsing every
file from disk on every request, even when nothing on disk had changed.
These tests prove the new mtime-based caches skip that work when files are
unchanged, and still pick up a real edit on the very next call.
"""

from __future__ import annotations

import time

from job_agent.candidate.parser import parse_candidate_profile
from job_agent.config.loader import _load_yaml


def test_load_yaml_returns_identical_content_on_repeat_call(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("a: 1\nb: 2\n")

    first = _load_yaml(path)
    second = _load_yaml(path)

    assert first == second == {"a": 1, "b": 2}


def test_load_yaml_picks_up_a_real_edit_immediately(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("a: 1\n")
    first = _load_yaml(path)
    assert first == {"a": 1}

    # Force a distinguishable mtime even on filesystems with coarse
    # (1-second) mtime resolution, so this test isn't flaky on any CI box.
    time.sleep(0.01)
    new_mtime = time.time() + 2
    path.write_text("a: 2\n")
    import os

    os.utime(path, (new_mtime, new_mtime))

    second = _load_yaml(path)
    assert second == {"a": 2}


def test_load_yaml_still_raises_on_missing_file(tmp_path):
    import pytest

    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(FileNotFoundError):
        _load_yaml(missing)


def test_load_yaml_still_raises_on_non_mapping_content(tmp_path):
    import pytest

    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n")
    with pytest.raises(ValueError):
        _load_yaml(path)


def test_parse_candidate_profile_cache_hit_has_fresh_parsed_at(real_config):
    """A cache hit must never make `parsed_at` look like a stale earlier
    request — callers (e.g. GET /api/candidate/profile) depend on it
    reading like "now"."""
    first = parse_candidate_profile(real_config)
    time.sleep(0.01)
    second = parse_candidate_profile(real_config)

    assert second.parsed_at > first.parsed_at
    # Everything else is identical (same underlying files/config, unchanged).
    assert second.skills == first.skills
    assert second.experience == first.experience
    assert second.identity_name == first.identity_name


def test_parse_candidate_profile_skips_reparse_when_nothing_changed(real_config, monkeypatch):
    """Directly tests the caching decision (not the markdown parsing
    itself, which real_profile-based tests already cover): the expensive
    `_parse_candidate_profile_uncached` must run exactly once for two
    calls with identical (files, config) inputs."""
    import job_agent.candidate.parser as parser_module

    call_count = {"n": 0}
    real_uncached = parser_module._parse_candidate_profile_uncached

    def _counting_uncached(config, cdir):
        call_count["n"] += 1
        return real_uncached(config, cdir)

    monkeypatch.setattr(parser_module, "_parse_candidate_profile_uncached", _counting_uncached)
    # Force a cache miss on the very first call regardless of test order.
    monkeypatch.setattr(parser_module, "_last_parse", None)

    parse_candidate_profile(real_config)
    parse_candidate_profile(real_config)

    assert call_count["n"] == 1, (
        f"expected the expensive parse to run once for two identical calls, "
        f"ran {call_count['n']} times"
    )


def test_parse_candidate_profile_reparses_after_a_real_file_edit(
    tmp_path, real_config, monkeypatch
):
    import os

    import job_agent.candidate.parser as parser_module
    from job_agent.config.loader import DEFAULT_CANDIDATE_DIR, AppConfig

    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    for name in parser_module._CANDIDATE_MD_FILE_NAMES:
        (candidate_dir / name).write_text((DEFAULT_CANDIDATE_DIR / name).read_text())

    config = AppConfig(
        env=real_config.env,
        profile=real_config.profile,
        preferences=real_config.preferences,
        sources=real_config.sources,
        automation=real_config.automation,
        rules=real_config.rules,
    )

    call_count = {"n": 0}
    real_uncached = parser_module._parse_candidate_profile_uncached

    def _counting_uncached(cfg, cdir):
        call_count["n"] += 1
        return real_uncached(cfg, cdir)

    monkeypatch.setattr(parser_module, "_parse_candidate_profile_uncached", _counting_uncached)
    monkeypatch.setattr(parser_module, "_last_parse", None)

    parse_candidate_profile(config, candidate_dir=candidate_dir)
    assert call_count["n"] == 1

    # A trailing blank line is a genuine file change (size + mtime both
    # differ) without depending on skills.md's exact structured format —
    # this test is about the caching decision, not markdown parsing rules.
    skills_md = candidate_dir / "skills.md"
    skills_md.write_text(skills_md.read_text() + "\n")
    new_mtime = time.time() + 2
    os.utime(skills_md, (new_mtime, new_mtime))

    parse_candidate_profile(config, candidate_dir=candidate_dir)
    assert call_count["n"] == 2, "editing a candidate/*.md file must trigger a real reparse"
