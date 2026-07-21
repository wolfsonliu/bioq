from bioq.errors import (  # noqa: F401
    CLIError, UsageError, AuthError, NotFoundError, JobFailedError,
    NoOutputError, GatewayError, ConflictError,
    EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_NOT_FOUND, EXIT_JOB_FAILED,
    EXIT_NO_OUTPUT, EXIT_GATEWAY,
)


def test_exit_codes_are_distinct():
    codes = [EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_NOT_FOUND,
             EXIT_JOB_FAILED, EXIT_NO_OUTPUT, EXIT_GATEWAY]
    assert codes == [0, 2, 3, 4, 5, 6, 7]
    assert len(set(codes)) == len(codes)


def test_clierror_carries_exit_code_and_message():
    err = AuthError("bad key")
    assert err.exit_code == EXIT_AUTH
    assert str(err) == "bad key"
    assert isinstance(err, CLIError)


def test_conflict_is_not_fatal_by_default():
    assert issubclass(ConflictError, CLIError)
