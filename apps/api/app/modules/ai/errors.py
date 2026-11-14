from app.core.errors import DependencyUnavailable


class AiUnavailable(DependencyUnavailable):
    code = "ai_unavailable"
    message = "AI assistance is temporarily unavailable"
