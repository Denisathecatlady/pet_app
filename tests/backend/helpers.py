"""Constants and helpers shared by the Django tests."""

import re

PASSWORD = "Kopretina-Rybník-2026"
OTHER_PASSWORD = "Javorový-List-9876"


def extract_link(body: str) -> str:
    """Return the path of the first http(s) link in an e-mail body."""
    match = re.search(r"https?://[^/\s]+(/\S*)", body)
    assert match, body
    return match.group(1)
