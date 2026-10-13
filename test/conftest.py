"""pytest configuration for the agent test suite.

test_backend.py is a manual Flask helper used to exercise the agent against a
local backend (it needs flask/flask_sock and is not an automated test), so it is
skipped during collection.
"""

collect_ignore = ["test_backend.py"]