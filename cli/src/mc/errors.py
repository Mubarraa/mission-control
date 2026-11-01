"""CLI errors and exit codes (design.md section 10)."""

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTH = 3  # 401 / 403
EXIT_NOT_FOUND = 4
EXIT_CONFLICT = 5  # 409 / 422
EXIT_SERVER = 6  # 5xx or unreachable


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = EXIT_USAGE, hint: str | None = None, body: dict | None = None):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        self.body = body or {}


def exit_code_for(status: int) -> int:
    if status in (401, 403):
        return EXIT_AUTH
    if status == 404:
        return EXIT_NOT_FOUND
    if status in (409, 422, 400):
        return EXIT_CONFLICT
    return EXIT_SERVER
