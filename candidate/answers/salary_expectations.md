question_type: SALARY
requires_human: true
---
config/preferences.yaml -> salary_preferences is currently UNKNOWN for currency, minimum_annual,
target_annual, and negotiable. Per rules.yaml (human_review_unknown), this question must always
route to HUMAN_REVIEW_REQUIRED until the candidate fills in real values. Never let an LLM infer or
estimate a market-rate salary figure to fill this gap.
