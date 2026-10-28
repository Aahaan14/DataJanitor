"""
DataJanitor — domain exceptions.

Services raise `DatasetError` subclasses; one handler in main.py converts them
into a consistent JSON body:  {"error": {"code": "...", "message": "..."}}.
Messages are written for end users and never include stack traces or paths.
"""


class DatasetError(Exception):
    """Base class for errors caused by the uploaded dataset or request."""

    status_code: int = 400
    code: str = "dataset_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidFileTypeError(DatasetError):
    status_code = 415
    code = "invalid_file_type"


class FileTooLargeError(DatasetError):
    status_code = 413
    code = "file_too_large"


class EmptyFileError(DatasetError):
    status_code = 400
    code = "empty_file"


class EncodingError(DatasetError):
    status_code = 422
    code = "unsupported_encoding"


class MalformedCSVError(DatasetError):
    status_code = 422
    code = "malformed_csv"


class DatasetLimitError(DatasetError):
    status_code = 422
    code = "dataset_limit_exceeded"


class DatasetNotFoundError(DatasetError):
    status_code = 404
    code = "dataset_not_found"


class PlanNotFoundError(DatasetError):
    status_code = 404
    code = "plan_not_found"


class ProposalNotFoundError(DatasetError):
    status_code = 404
    code = "proposal_not_found"


class PlanInactiveError(DatasetError):
    """The plan can no longer be acted on (superseded or stale)."""
    status_code = 409

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ConflictingProposalError(DatasetError):
    status_code = 409
    code = "conflicting_proposal"


class InvalidDecisionError(DatasetError):
    status_code = 422
    code = "invalid_decision"


class DatasetUnavailableError(DatasetError):
    """The dataset record exists but its file was deleted or expired."""
    status_code = 410
    code = "dataset_unavailable"


class DatasetModifiedError(DatasetError):
    status_code = 409
    code = "dataset_modified"


class StorageError(DatasetError):
    """Database failure. The message is deliberately generic (no internals)."""
    status_code = 500
    code = "database_error"


class NoApprovedRepairsError(DatasetError):
    status_code = 422
    code = "no_approved_repairs"


class OutputIntegrityError(DatasetError):
    """The generated file did not match exactly the approved changes."""
    status_code = 500
    code = "output_integrity_error"


class CleanedNotFoundError(DatasetError):
    status_code = 404
    code = "cleaned_not_found"


class CleanedUnavailableError(DatasetError):
    status_code = 410
    code = "cleaned_unavailable"


class EmailNotConfiguredError(DatasetError):
    status_code = 409
    code = "email_not_configured"


class ReportNotAvailableError(DatasetError):
    """A report can only be made for a completed scan / cleaning run."""
    status_code = 409
    code = "report_not_available"


class ReportNotFoundError(DatasetError):
    status_code = 404
    code = "report_not_found"


class ReportAlreadySentError(DatasetError):
    status_code = 409
    code = "report_already_sent"


class EmailDeliveryError(Exception):
    """SMTP delivery failed. `message` is safe to store and show (no secrets, no server text)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
