"""Exit-code taxonomy + CLI exception hierarchy.

Every user-facing failure maps to a stable exit code so scripts can branch.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2          # bad args / usage
EXIT_AUTH = 3           # 401 / 403
EXIT_NOT_FOUND = 4      # 404 (unknown service or job)
EXIT_JOB_FAILED = 5     # terminal status == failed / cancelled
EXIT_NO_OUTPUT = 6      # status == completed but no results.zip (FC-status masking)
EXIT_GATEWAY = 7        # 5xx / 502 dispatch/download / transport
EXIT_INTERRUPT = 130    # SIGINT


class CLIError(Exception):
    exit_code = EXIT_GATEWAY

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(CLIError):
    exit_code = EXIT_USAGE


class AuthError(CLIError):
    exit_code = EXIT_AUTH


class NotFoundError(CLIError):
    exit_code = EXIT_NOT_FOUND


class JobFailedError(CLIError):
    exit_code = EXIT_JOB_FAILED


class NoOutputError(CLIError):
    exit_code = EXIT_NO_OUTPUT


class GatewayError(CLIError):
    exit_code = EXIT_GATEWAY


class ConflictError(CLIError):
    """409 from the gateway — job_id already exists. `run` treats this as
    'already submitted' and proceeds to poll, so it is not fatal by itself."""
    exit_code = EXIT_GATEWAY
