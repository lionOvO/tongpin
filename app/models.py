from typing import Literal
from pydantic import BaseModel, Field

Origin = Literal["synthetic", "real"]
Side = Literal["enterprise", "candidate"]


class JobInput(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    jd: str = Field(min_length=20, max_length=30000)
    data_origin: Origin = "synthetic"
    manual_profile: dict | None = None


class Requirement(BaseModel):
    skill: str
    required_level: int = Field(ge=1, le=4)
    quote: str = Field(min_length=1)
    hard: bool = True


class JobProfile(BaseModel):
    requirements: list[Requirement]
    direction: str
    education: Literal["大专", "本科", "硕士", "博士"] | None = None


class JobConfirmation(BaseModel):
    profile: JobProfile
    expected_version: int = Field(ge=1)


class ResumeInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=20, max_length=50000)
    data_origin: Origin = "synthetic"


class PreferenceInput(BaseModel):
    side: Side
    job_id: str | None = None
    resume_id: str | None = None
    dimensions: dict[str, str | None]
    dimension_version: str
    ambience_text: str = Field(default="", max_length=2000)
    share_with_counterparty: bool = False


class MatchInput(BaseModel):
    job_id: str
    resume_id: str


class FitInput(BaseModel):
    resume_id: str
    job_id: str | None = None
    jd: str | None = Field(default=None, min_length=20, max_length=30000)
    title: str = Field(default="我的目标岗位",min_length=2,max_length=100)


class AssessmentInput(BaseModel):
    job_id: str
    resume_ids: list[str] = Field(min_length=1, max_length=50)


class ReviewInput(BaseModel):
    report_id: str
    action: Literal["确认", "单维改档", "整份打回"]
    dimension_id: str | None = None
    tier_after: Literal["B1", "B2", "B3", "B4", "B5", "insufficient"] | None = None
    reason: str = Field(min_length=2, max_length=1000)


class BriefInput(BaseModel):
    job_id: str
    answers: dict[str, str] = Field(default_factory=dict)


class CompareInput(BaseModel):
    resume_id: str
    job_texts: list[str] = Field(min_length=2, max_length=20)


class TierEvidence(BaseModel):
    dimension_id: Literal["D1", "D2", "D3", "D4", "D5"]
    tier: Literal["B1", "B2", "B3", "B4", "B5", "insufficient"]
    tier_range: list[str] = Field(default_factory=list)
    evidence: list[str]
    rationale: str


class SkillEvidence(BaseModel):
    skill: str
    evidence_level: int = Field(ge=0, le=4)
    evidence: list[str]
    self_reported: str = ""


class EvaluationOutput(BaseModel):
    dimensions: list[TierEvidence]
    skills: list[SkillEvidence]
