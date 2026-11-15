from app.core.errors import Conflict, DependencyUnavailable, ValidationFailed


class InvoiceNotPayable(Conflict):
    code, message = "invoice_not_payable", "This invoice is not open for payment"


class BillingEmailRequired(ValidationFailed):
    code, message = "billing_email_required", "Add a billing email to your organization first"


class PaymentProviderDown(DependencyUnavailable):
    code, message = "payments_unavailable", "Payments are unavailable right now. Try again."


class NothingToRefund(Conflict):
    code, message = "nothing_to_refund", "This invoice has no completed payment to refund"
