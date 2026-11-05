from typing import Literal, Annotated
from pydantic import BaseModel, Field, field_validator, model_validator

Origin = Literal["synthetic", "real"]
Side = Literal["enterprise", "candidate"]


class JobInput(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    jd: str = Field(min_length=20, max_length=30000)
    data_origin: Origin = "synthetic"
    manual_profile: dict | None = None


class ReferenceJobInput(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    jd: str = Field(min_length=20, max_length=30000)
    data_origin: Origin = 'real'

    @field_validator('title', 'jd', mode='before')
    @classmethod
    def strip_reference(cls, value):
        return value.strip() if isinstance(value, str) else value


class Requirement(BaseModel):
    skill: str = Field(min_length=1, max_length=100)
    required_level: int = Field(ge=1, le=4)
    quote: str = Field(min_length=1)
    hard: bool = True

    @field_validator('skill')
    @classmethod
    def clean_skill(cls, value):
        if not value.strip(): raise ValueError('技能名称不能为空')
        return value.strip()


class JobProfile(BaseModel):
    requirements: list[Requirement]
    direction: str
    education: Literal["大专", "本科", "硕士", "博士"] | None = None

    @field_validator('requirements')
    @classmethod
    def unique_requirements(cls, values):
        names = [r.skill.casefold() for r in values]
        if len(names) != len(set(names)): raise ValueError('同一技能只能填写一条要求')
        return values


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


class JobVisibility(BaseModel):
    published: bool


class MatchInput(BaseModel):
    share_with_job: bool = False
    job_id: str
    resume_id: str


class FitInput(BaseModel):
    resume_id: str
    job_id: str | None = None
    jd: str | None = Field(default=None, min_length=20, max_length=30000)
    title: str = Field(default="我的目标岗位",min_length=2,max_length=100)
    manual_profile: JobProfile | None = None


class AssessmentInput(BaseModel):
    job_id: str
    resume_ids: list[str] = Field(min_length=1, max_length=50)


class ReviewInput(BaseModel):
    report_id: str
    action: Literal["确认", "单维改档", "整份打回"]
    dimension_id: str | None = None
    tier_after: Literal["B1", "B2", "B3", "B4", "B5", "insufficient"] | None = None
    reason: str = Field(min_length=2, max_length=1000)


class BriefRequirement(BaseModel):
    skill: str = Field(min_length=1, max_length=100)
    type: Literal['硬性', '加分', '可培养']
    priority: Literal['P0', 'P1', 'P2']


class BriefInput(BaseModel):
    job_id: str
    answers: dict[str, str] = Field(default_factory=dict)
    requirement_overrides: list[BriefRequirement] = Field(default_factory=list, max_length=100)


class CompareInput(BaseModel):
    resume_id: str
    job_texts: list[Annotated[str, Field(min_length=20, max_length=30000)]] = Field(default_factory=list, max_length=20)
    job_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def one_source(self):
        self.job_texts = [text.strip() for text in self.job_texts]
        if bool(self.job_texts) == bool(self.job_ids) or self.job_texts and len(self.job_texts) < 2:
            raise ValueError('请选择 1–20 个已有岗位，或填写 2–20 个岗位描述。')
        if any(len(text) < 20 for text in self.job_texts):
            raise ValueError('每个岗位描述至少需要 20 个有效字符。')
        if len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError('岗位不能重复选择。')
        return self


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
