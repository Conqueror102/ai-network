from app.core.errors import Conflict, DependencyUnavailable, Unauthenticated, ValidationFailed


class InvalidDestination(ValidationFailed):
    code, message = "invalid_destination", "That phone number or email is not valid"


class ChallengeFailed(ValidationFailed):
    code, message = "challenge_failed", "Verification challenge failed"


class OtpInvalid(Unauthenticated):
    code, message = "otp_invalid", "That code is not correct"


class OtpExpired(Unauthenticated):
    code, message = "otp_expired", "That code has expired"


class OtpAttemptsExceeded(Unauthenticated):
    code, message = "otp_attempts_exceeded", "Too many wrong attempts. Request a new code"


class OtpUndeliverable(DependencyUnavailable):
    code, message = "otp_undeliverable", "We could not send the code. Try another channel"


class RefreshInvalid(Unauthenticated):
    code, message = "refresh_invalid", "Session expired. Sign in again"


class RefreshReused(Unauthenticated):
    code, message = "refresh_reused", "Session revoked. Sign in again"


class ContentRejected(ValidationFailed):
    code, message = "content_rejected", "That text is not allowed. Please rephrase it"


class PhotoNotUploaded(Conflict):
    code, message = "photo_not_uploaded", "Upload the photo before committing it"
