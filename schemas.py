"""Validated request models shared by PathForge API routes."""

from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr


class ChatMessage(BaseModel):
    message: str


class LearningAssistantMessage(BaseModel):
    message: str
    attachment_name: Optional[str] = None
    attachment_text: Optional[str] = None
    evaluation_mode: Optional[str] = "auto"
    target_industry: Optional[str] = None
    target_job_description: Optional[str] = None
    career_stage: Optional[str] = None


class LearningAssistantDocument(BaseModel):
    filename: str
    content_base64: str


class ResumeEvaluationRequest(BaseModel):
    resume_text: str
    job_description: Optional[str] = None
    target_role: Optional[str] = None
    target_industry: Optional[str] = None
    career_stage: Optional[Literal[
        "auto", "student", "entry_level", "career_changer", "mid_level", "executive"
    ]] = "auto"


class MockInterviewFlaggedAttempt(BaseModel):
    question_index: int
    answer: str


class MockInterviewMessage(BaseModel):
    role: str
    interview_type: str
    question_index: int
    answer: Optional[str] = None
    answers: Optional[List[str]] = None
    flagged_attempts: Optional[List[MockInterviewFlaggedAttempt]] = None


class Job(BaseModel):
    title: str
    company: str
    location: str
    pay: str
    description: str
    requirements: Optional[str] = None
    preferred_qualifications: Optional[str] = None
    schedule: str
    experience: str
    category: str
    application_method: str = "pathforge"
    application_url: Optional[str] = None
    status: str = "active"
    application_deadline: Optional[str] = None


class JobStatusUpdate(BaseModel):
    status: str


class SavedSearchInput(BaseModel):
    name: str
    keyword: str = ""
    location: str = ""
    location_scope: str = "us"
    category: str = "all"
    employment_type: str = "all"
    remote_filter: str = "all"
    experience: str = "all"
    location_mode: str = "nearby"
    remote_eligibility: str = "all"
    age_fit: str = "all"
    date_posted: str = "all"
    listing_quality: str = "all"
    application_feature: str = "all"
    minimum_pay: float = 0
    exclusions: str = ""
    exclude_terms: str = ""
    frequency: str = "daily"
    is_enabled: bool = True


class EmployerWorkspaceCreate(BaseModel):
    company_name: str
    website: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    current_password: str


class PrivacySettingsUpdate(BaseModel):
    allow_personalized_guidance: bool = True
    allow_employer_discovery: bool = False
    security_notifications: bool = True


class ConversationCreate(BaseModel):
    application_id: int


class DirectMessageCreate(BaseModel):
    body: str


class MessageReportCreate(BaseModel):
    reason: str


class ConversationBlockUpdate(BaseModel):
    blocked: bool


class EmployerCodeRedemption(BaseModel):
    code: str


class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    career_stage: Optional[str] = None
    career_interests: Optional[str] = None
    preferred_industries: Optional[str] = None
    skills: Optional[str] = None
    experience_level: Optional[str] = None
    preferred_location: Optional[str] = None
    schedule_preference: Optional[str] = None
    work_preference: Optional[str] = None
    desired_pay: Optional[str] = None
    maximum_commute_distance: Optional[int] = None
    maximum_commute_time: Optional[int] = None
    pay_period: Optional[str] = None
    minimum_base_pay: Optional[float] = None
    career_goals: Optional[str] = None


class ApplicationCreate(BaseModel):
    job_id: int
    application_method: str
    status: str = "Interested"
    applied_at: Optional[str] = None
    interview_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None


class ExternalApplicationCapture(BaseModel):
    title: str
    company: str
    location: str = "Not listed"
    application_url: Optional[str] = None
    applied_at: Optional[str] = None
    status: str = "Applied"
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[str] = None
    applied_at: Optional[str] = None
    interview_date: Optional[str] = None
    interview_time: Optional[str] = None
    interview_format: Optional[str] = None
    interview_location: Optional[str] = None
    interview_details: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None


class ApplicationQuestionInput(BaseModel):
    question_text: str
    field_type: str = "short_text"
    is_required: bool = True


class ApplicationFormUpdate(BaseModel):
    questions: List[ApplicationQuestionInput]


class ApplicationAnswerInput(BaseModel):
    question_id: int
    answer_text: Optional[str] = None


class InternalApplicationSubmit(BaseModel):
    answers: List[ApplicationAnswerInput]


class EmployerApplicationUpdate(BaseModel):
    status: Optional[str] = None
    interview_date: Optional[str] = None
    interview_time: Optional[str] = None
    interview_format: Optional[str] = None
    interview_location: Optional[str] = None
    interview_details: Optional[str] = None
    employer_notes: Optional[str] = None


class LearningProgressUpdate(BaseModel):
    status: str


class CompanyProfileUpdate(BaseModel):
    company_name: str
    company_description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    hiring_preferences: Optional[str] = None
