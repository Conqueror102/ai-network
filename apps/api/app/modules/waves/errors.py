from app.core.errors import Conflict, DependencyUnavailable, Forbidden, NotFound, ValidationFailed


class WaveAlreadyExists(Conflict):
    code, message = "wave_already_exists", "You already reached out to this person"


class RecipientUnavailable(NotFound):
    """Hidden, blocked, gone: one answer for all of them, by design (03 §6)."""

    code, message = "recipient_unavailable", "This person is not available"


class NoteRejected(ValidationFailed):
    code, message = "note_rejected", "Try different wording"


class NoteUnavailable(DependencyUnavailable):
    code, message = "note_unavailable", "Notes are unavailable right now. Send without one."


class WaveNotPending(Conflict):
    code, message = "wave_not_pending", "This intro was already answered"


class WavesPaused(Forbidden):
    code, message = "waves_paused", "Intros are paused for you at this event"


class ProfileRequired(Forbidden):
    code, message = "profile_required", "Create your event card first"
