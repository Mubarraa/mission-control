from enum import StrEnum


class Role(StrEnum):
    DIRECTOR = "DIRECTOR"
    LEAD = "LEAD"
    CREW = "CREW"


class MissionState(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class MissionAction(StrEnum):
    SUBMIT = "submit"
    WITHDRAW = "withdraw"
    APPROVE = "approve"
    REJECT = "reject"
    START = "start"
    COMPLETE = "complete"
    ABORT = "abort"
    CANCEL = "cancel"


class AssignmentState(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class AssignmentSource(StrEnum):
    MATCHER = "MATCHER"
    MANUAL = "MANUAL"


class SkillStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class UnavailabilityCategory(StrEnum):
    LEAVE = "LEAVE"
    TRAINING = "TRAINING"
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


PROFICIENCY_LABELS = {1: "Awareness", 2: "Novice", 3: "Competent", 4: "Proficient", 5: "Expert"}
