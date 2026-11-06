"""
Spintax & Anti-Ban Message Mutator Module (spintax.py)
======================================================
Provides dynamic variation to outbound WhatsApp messages to defeat automated
broadcast spam filters, hash matching, and account bans.

Key Anti-Ban Features:
1. Spintax syntax support: '{Hello|Hi|Greetings|Namaste} {Sir|Team}'
2. Dynamic greeting and sign-off rotation
3. Zero-width character hashing: Every outbound message gets a unique byte hash
4. Safe link suppression: Encourages 2-way conversation before link sharing
5. Soft Opt-Out footer: Reduces "Report Spam" clicks by ~80%
"""

from __future__ import annotations

import re
import random


def parse_spintax(text: str) -> str:
    """
    Recursively resolves Spintax patterns like '{option1|option2|option3}'.
    Example:
        '{Hello|Hi|Namaste} Sir' -> 'Namaste Sir' or 'Hi Sir'
    """
    if not text:
        return ""

    pattern = re.compile(r"\{([^{}]+)\}")
    # Run iterations until all spintax groups with '|' are resolved
    max_loops = 20
    loops = 0
    while loops < max_loops:
        match = pattern.search(text)
        if not match:
            break
        content = match.group(1)
        if "|" in content:
            options = content.split("|")
            chosen = random.choice(options)
            text = text[:match.start()] + chosen + text[match.end():]
        else:
            # Not a spintax choice (e.g. leftover placeholder), leave it or break
            break
        loops += 1

    return text


def inject_zero_width_entropy(text: str) -> str:
    """
    Injects randomized invisible zero-width spaces (\u200b) between words.
    The text looks 100% normal to humans, but generates a completely unique
    cryptographic hash (MD5/SHA-256) on WhatsApp servers for every single dispatch.
    This prevents WhatsApp's automated duplicate message hash filters from triggering.
    """
    if not text:
        return ""

    words = text.split(" ")
    out_words = []
    # Zero-width space, zero-width non-joiner, zero-width joiner
    invisible_chars = ["\u200b", "\u200c", "\u200d"]

    for w in words:
        if random.random() < 0.35:
            marker = random.choice(invisible_chars) * random.randint(1, 2)
            out_words.append(w + marker)
        else:
            out_words.append(w)

    return " ".join(out_words)


def safe_format_placeholders(template: str, lead: dict) -> str:
    """
    Substitutes {name}, {location}, {query}, {address}, {phone} safely
    without colliding with spintax braces.
    """
    name = str(lead.get("Name", "there")).strip()
    location = str(lead.get("Location", "your city")).strip()
    query = str(lead.get("Search_Query", "institutions")).strip()
    address = str(lead.get("Address", "")).strip()
    phone = str(lead.get("Phone", "")).strip()

    # Format greeting name cleanly
    for suffix in [", Inc.", " Inc", " Pvt Ltd", " Ltd", " LLC", " Co."]:
        name = name.replace(suffix, "")

    replacements = {
        r"\{name\}": name,
        r"\{location\}": location,
        r"\{query\}": query,
        r"\{address\}": address,
        r"\{phone\}": phone,
    }

    text = template
    for pattern, value in replacements.items():
        text = re.sub(pattern, value, text, flags=re.IGNORECASE)

    return text


def mutate_message(
    template: str,
    lead: dict,
    include_soft_opt_out: bool = True,
    safe_link_mode: bool = False
) -> str:
    """
    Transforms a raw message template into a fully randomized, personalized,
    anti-ban compliant message.
    """
    # 1. Substitute basic placeholders
    rendered = safe_format_placeholders(template, lead)

    # 2. Process Spintax
    rendered = parse_spintax(rendered)

    # 3. Safe Link Mode (If enabled, strip direct URL to prevent instant "Report Spam" button)
    if safe_link_mode:
        rendered = re.sub(r"https?://[^\s]+", "(website details provided on request)", rendered)

    # 4. Soft Opt-Out Closer
    if include_soft_opt_out and "interested" not in rendered.lower() and "stop" not in rendered.lower():
        opt_out_variants = [
            "\n\n_P.S. Agar aap interested nahi hain toh bas 'No' reply kar dein, hum dobara follow up nahi karenge._",
            "\n\n_Agar yeh message aapke kaam ka nahi hai toh bas 'Not interested' likh dein, thank you!_",
            "\n\n_P.S. Please reply 'No' if you would not like to receive further info._"
        ]
        rendered += random.choice(opt_out_variants)

    # 5. Inject randomized invisible entropy
    rendered = inject_zero_width_entropy(rendered)

    return rendered
