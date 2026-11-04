"""
Blacklist & Banned Institutes Filter Module (blacklist.py)
==========================================================
Protects the automation pipeline from messaging or scraping banned institutes.
Specifically blocks major chains like:
- Allen Career Institute (allen)
- Aakash / Akash Institute (aakash, akash, aesl)
- Physics Wallah (physics wallah, physicswallah, pw)
along with any custom entries defined in 'banned_institutes.txt'.
"""

from __future__ import annotations

import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BLACKLIST_FILE = os.path.join(BASE_DIR, "banned_institutes.txt")

# Core built-in keywords/regex patterns (case-insensitive)
DEFAULT_BANNED_RULES = [
    r"\ballen\b",                 # Allen Career Institute, ALLEN Kota, etc.
    r"\baakash\b",                # Aakash Institute, Aakash BYJU'S, etc.
    r"\bakash\b",                 # Akash Institute, Akash Classes, etc.
    r"physics\s*wallah",          # Physics Wallah, Physics Wallah Vidyapeeth, etc.
    r"physicswallah",             # PhysicsWallah
    r"pw\s+vidyapeeth",           # PW Vidyapeeth
    r"pw\s+pathshala",            # PW Pathshala
    r"pw\s+coaching",             # PW Coaching
    r"\bpw\b",                    # Standalone PW
    r"\baesl\b",                  # Aakash Educational Services Limited
]


def load_banned_patterns() -> list[str]:
    """
    Loads all active banned keywords and patterns from 'banned_institutes.txt'
    merged with the default hardcoded rules.
    """
    patterns = list(DEFAULT_BANNED_RULES)

    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if line and not line.startswith("#"):
                        # If simple word without regex symbols, convert to safe word-boundary regex
                        if re.match(r"^[a-zA-Z0-9\s]+$", line):
                            clean_words = r"\s+".join(re.escape(w) for w in line.split())
                            pat = rf"\b{clean_words}\b"
                        else:
                            pat = line

                        if pat not in patterns:
                            patterns.append(pat)
        except Exception:
            pass

    return patterns


def is_banned_institute(name: str) -> tuple[bool, str]:
    """
    Checks whether a business / institute name matches any banned institute.
    
    Returns:
        (is_banned: bool, reason: str)
        Example: (True, "Matched banned institute pattern: '\\ballen\\b'")
                 (False, "")
    """
    if not name or not isinstance(name, str):
        return False, ""

    clean_name = name.strip()
    patterns = load_banned_patterns()

    for pattern in patterns:
        try:
            if re.search(pattern, clean_name, re.IGNORECASE):
                # Format a friendly reason for logs
                human_keyword = pattern.replace(r"\b", "").replace(r"\s+", " ").strip()
                return True, f"Banned Institute ({human_keyword})"
        except re.error:
            # Fallback to direct lowercase substring matching if regex compilation fails
            raw_target = pattern.replace(r"\b", "").strip().lower()
            if raw_target and raw_target in clean_name.lower():
                return True, f"Banned Institute ({raw_target})"

    return False, ""


def add_banned_institute(keyword_or_pattern: str) -> bool:
    """
    Appends a new banned keyword or institute to 'banned_institutes.txt'.
    """
    cleaned = keyword_or_pattern.strip()
    if not cleaned:
        return False

    existing = load_banned_patterns()
    is_already_banned, _ = is_banned_institute(cleaned)
    if is_already_banned:
        return True

    try:
        with open(BLACKLIST_FILE, "a", encoding="utf-8") as f:
            f.write(f"{cleaned}\n")
        return True
    except Exception:
        return False


def get_all_banned_keywords() -> list[str]:
    """
    Returns clean user-friendly list of all active banned keywords.
    """
    results = []
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        results.append(line)
        except Exception:
            pass

    # Ensure defaults are included
    defaults_friendly = ["allen", "aakash", "akash", "physics wallah", "physicswallah", "pw vidyapeeth", "pw"]
    for d in defaults_friendly:
        if d not in results:
            results.append(d)

    return results

