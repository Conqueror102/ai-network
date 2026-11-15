from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed


class RadarRequiresPhoto(Conflict):
    code, message = "radar_requires_photo", "Add an approved photo to be discoverable on radar"


class NotVisible(NotFound):
    code, message = "not_visible", "That profile is not available"


class ProfileRequired(Forbidden):
    code, message = "profile_required", "Create your event card first"


class DirectoryRequiresVisibility(Forbidden):
    code = "directory_requires_visibility"
    message = "Make yourself visible in the directory to browse it"


class GoalLimit(Conflict):
    code, message = "goal_limit_reached", "You can have up to 3 goals per event"


class PriorityTaken(Conflict):
    code, message = "goal_priority_taken", "You already have a goal with that priority"


class ContentRejected(ValidationFailed):
    code, message = "content_rejected", "That text is not allowed. Please rephrase it"
