from app.core.errors import Conflict, NotFound, ValidationFailed


class ExchangeTokenInvalid(ValidationFailed):
    code, message = "exchange_token_invalid", "This code has expired. Ask them to show it again."


class ExchangeNotFound(NotFound):
    code, message = "exchange_not_found", "This exchange has expired. Scan again."


class ExchangeSelf(Conflict):
    code, message = "exchange_self", "You cannot exchange with yourself"
