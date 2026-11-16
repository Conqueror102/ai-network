from app.core.errors import Conflict, Forbidden, RateLimited, ValidationFailed


class QrInvalid(ValidationFailed):
    code, message = "qr_invalid", "That QR code is not valid for this event"


class QrStale(ValidationFailed):
    code, message = "qr_stale", "That QR code has expired. Scan the live screen at the door"


class CheckinNotApproved(Forbidden):
    code, message = "checkin_not_approved", "Your registration has not been approved yet"


class EventNotLive(Conflict):
    code, message = "event_not_live", "Check-in is not open for this event"


class EventFull(Conflict):
    code, message = "event_full", "This event is at capacity"


class InvalidTransition(Conflict):
    code, message = "invalid_status_transition", "That status change is not allowed"


class AnnouncementRateLimited(RateLimited):
    code, message = "announcement_rate_limited", "Wait before sending another announcement"


class ContentRejected(ValidationFailed):
    code, message = "content_rejected", "That text is not allowed. Please rephrase it"


class SpotExists(Conflict):
    code, message = "spot_exists", "This event already has a meeting spot with that name"


class TooManySpots(ValidationFailed):
    code, message = "too_many_spots", "An event can have at most 20 active meeting spots"
