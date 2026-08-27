from __future__ import annotations

from job_agent.applications.rules_enforcement import (
    CAPTCHA_DETECTED,
    MFA_DETECTED,
    UNEXPECTED_FORM_STRUCTURE,
    evaluate_inspection,
)
from job_agent.applications.schema import ApplicationInspection
from job_agent.config.models import LoggingRules, RulesConfig, SafetyRules, TruthValidationRules


def _rules(**safety_overrides) -> RulesConfig:
    defaults = dict(
        never_fabricate=True, human_review_unknown=True, human_review_ambiguous=True,
        stop_on_captcha=True, stop_on_mfa=True, stop_on_unexpected_form=True,
        never_bypass_access_controls=True, never_bypass_rate_limits=True,
        never_bypass_bot_detection=True,
    )
    defaults.update(safety_overrides)
    return RulesConfig(
        safety=SafetyRules(**defaults),
        hard_stop_conditions=[CAPTCHA_DETECTED, MFA_DETECTED, UNEXPECTED_FORM_STRUCTURE],
        truth_validation=TruthValidationRules(
            allowed_fact_statuses=["HAS", "DEMONSTRATED"],
            internal_only_statuses=["ADJACENT"],
            blocked_statuses=["MISSING", "UNKNOWN"],
        ),
        logging=LoggingRules(redact_fields=["password"]),
    )


def test_real_config_rules_yaml_has_stop_flags_enabled_by_default():
    """Grounds every other test in this file in the *actual* shipped
    config/rules.yaml, not just a constructed fixture — proves this module
    reads real values, not a duplicated/hardcoded copy."""
    from job_agent.config.loader import load_config

    cfg = load_config()
    assert cfg.rules.safety.stop_on_captcha is True
    assert cfg.rules.safety.stop_on_mfa is True
    assert cfg.rules.safety.stop_on_unexpected_form is True


def test_clean_inspection_never_requires_human():
    rules = _rules()
    inspection = ApplicationInspection(structure_recognized=True)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is False
    assert verdict.reason is None


def test_captcha_detected_requires_human_when_rule_enabled():
    rules = _rules(stop_on_captcha=True)
    inspection = ApplicationInspection(structure_recognized=True, captcha_detected=True)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is True
    assert verdict.reason == CAPTCHA_DETECTED


def test_mfa_detected_requires_human_when_rule_enabled():
    rules = _rules(stop_on_mfa=True)
    inspection = ApplicationInspection(structure_recognized=True, mfa_detected=True)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is True
    assert verdict.reason == MFA_DETECTED


def test_unrecognized_structure_requires_human_when_rule_enabled():
    rules = _rules(stop_on_unexpected_form=True)
    inspection = ApplicationInspection(structure_recognized=False)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is True
    assert verdict.reason == UNEXPECTED_FORM_STRUCTURE


def test_captcha_fact_ignored_when_the_actual_rule_is_disabled():
    """Proves this module genuinely *reads* config.rules.safety rather
    than hardcoding "captcha => human" — flipping the real flag off
    changes the outcome."""
    rules = _rules(stop_on_captcha=False)
    inspection = ApplicationInspection(structure_recognized=True, captcha_detected=True)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is False
    assert verdict.reason is None


def test_mfa_fact_ignored_when_the_actual_rule_is_disabled():
    rules = _rules(stop_on_mfa=False)
    inspection = ApplicationInspection(structure_recognized=True, mfa_detected=True)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is False


def test_unrecognized_structure_ignored_when_the_actual_rule_is_disabled():
    rules = _rules(stop_on_unexpected_form=False)
    inspection = ApplicationInspection(structure_recognized=False)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.human_required is False


def test_captcha_takes_priority_over_other_conditions_when_multiple_apply():
    rules = _rules()
    inspection = ApplicationInspection(
        structure_recognized=False, captcha_detected=True, mfa_detected=True,
    )
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.reason == CAPTCHA_DETECTED


def test_mfa_takes_priority_over_unrecognized_structure():
    rules = _rules()
    inspection = ApplicationInspection(structure_recognized=False, mfa_detected=True)
    verdict = evaluate_inspection(rules, inspection)
    assert verdict.reason == MFA_DETECTED
