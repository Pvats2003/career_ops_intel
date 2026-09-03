from job_agent.resume.errors import ResumeConsistencyError, ResumeExtractionError
from job_agent.resume.extractor import extract_resume_text
from job_agent.resume.service import ProfileVersionResult, create_profile_version
from job_agent.resume.tailor import TailoredResume, tailor_resume_for_job
from job_agent.resume.validator import ValidationIssue, validate_profile_against_resume

__all__ = [
    "ProfileVersionResult",
    "ResumeConsistencyError",
    "ResumeExtractionError",
    "TailoredResume",
    "ValidationIssue",
    "create_profile_version",
    "extract_resume_text",
    "tailor_resume_for_job",
    "validate_profile_against_resume",
]
