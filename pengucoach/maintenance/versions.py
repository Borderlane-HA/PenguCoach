"""Release version ordering shared by the update notice and the host updater.

Kept dependency-free: the maintenance agent runs outside the application venv.
"""
import re

_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|rc)[.-]?(\d+(?:\.\d+)*))?", re.I)
_STAGES = {"alpha": 0, "beta": 1, "rc": 2, None: 3}


def display(value):
    """Map PEP 440 package versions (0.1.0a43.post1) to release labels (0.1.0-alpha.43.1)."""
    raw = str(value).strip()
    for pattern in (r"(\d+\.\d+\.\d+)-alpha\.(\d+)\.post(\d+)", r"(\d+\.\d+\.\d+)a(\d+)\.post(\d+)"):
        match = re.fullmatch(pattern, raw)
        if match:return f"{match.group(1)}-alpha.{match.group(2)}.{match.group(3)}"
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", raw)
    if match:return f"{match.group(1)}-alpha.{match.group(2)}"
    return raw


def version_key(value):
    match = _PATTERN.fullmatch(display(value))
    if not match:
        return None
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch), _STAGES[stage.lower() if stage else None],
            tuple(map(int, number.split("."))) if number else ())


def eligible(tag, installed_key):
    """Stable installations only follow stable releases; pre-releases follow all."""
    key = version_key(tag)
    if key is None:return None
    if installed_key is not None and installed_key[3] == 3 and key[3] < 3:return None
    return key


def newest_tag(tags, installed):
    """Return (tag, key) of the newest eligible release tag, or (None, None)."""
    current = version_key(installed)
    best = (None, None)
    for tag in tags:
        key = eligible(tag, current)
        if key is not None and (best[1] is None or key > best[1]):best = (tag, key)
    return best
