"""Bass practice tooling: `practice`, `loop` and `rearrange`."""

import warnings

# pydub (unmaintained) has non-raw regex strings that Python 3.12 flags as a
# SyntaxWarning when it compiles the file. Nothing here can fix it, and it
# printed on every `practice serve`. A compile-time warning names the file path
# as its module, not a dotted name, so the match is on the path; set here
# because this package is imported before any module that imports pydub.
warnings.filterwarnings("ignore", category=SyntaxWarning, module=r".*[/\\]pydub[/\\].*")
