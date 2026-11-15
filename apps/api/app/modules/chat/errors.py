from app.core.errors import Conflict, NotFound, ValidationFailed


class ConversationNotFound(NotFound):
    """Also what both sides of a blocked pair get: the thread is gone for both (01 §14.1)."""

    code, message = "conversation_not_found", "Conversation not found"


class MeetInvalid(ValidationFailed):
    code, message = "meet_invalid", "Pick one of the event's meeting points and a future time"


class MeetNotOpen(Conflict):
    code, message = "meet_not_open", "This proposal can no longer be accepted"
