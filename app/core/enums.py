from enum import Enum


class OutcomeState(str, Enum):
    DRAFT = "draft"
    CLARIFYING = "clarifying"
    PLANNED = "planned"
    RUNNING = "running"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    DELIVERED = "delivered"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanStepKind(str, Enum):
    READ = "read"
    REASON = "reason"
    WRITE = "write"
    APPROVAL = "approval"


class PlanStepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class RunState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunEventTag(str, Enum):
    AUTH = "auth"
    READ = "read"
    FILTER = "filter"
    RULE = "rule"
    SIGNAL = "signal"
    GAP = "gap"
    INSIGHT = "insight"
    NOTIFY = "notify"
    REASON = "reason"


class ToolId(str, Enum):
    SLACK = "slack"
    GMAIL = "gmail"
    GCAL = "gcal"
    GDRIVE = "gdrive"
    NOTION = "notion"
    LINEAR = "linear"
    JIRA = "jira"
    GITHUB = "github"
    FIGMA = "figma"
    SALESFORCE = "salesforce"
    HUBSPOT = "hubspot"
    ASANA = "asana"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"


TIER_LIMITS = {
    "free": {"runs_per_month_after_trial": 3, "connections": 3, "seats": 1},
    "starter": {"runs_per_month_after_trial": None, "connections": 14, "seats": 1},
    "business": {"runs_per_month_after_trial": None, "connections": 14, "seats": 1},
    "teams": {"runs_per_month_after_trial": None, "connections": 14, "seats": 10},
    "enterprise": {"runs_per_month_after_trial": None, "connections": None, "seats": None},
}