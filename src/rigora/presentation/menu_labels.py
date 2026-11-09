"""Literal Qt menu labels and their matching plain-text search/status names."""

import re


def menu_text(text: str) -> str:
    """Escape a literal command or user-supplied name for Qt's mnemonic-aware controls."""
    return text.replace("&", "&&")


def display_text(text: str) -> str:
    """Decode Qt mnemonic markers while preserving escaped ampersands and ellipses."""
    return re.sub(r"&(.?)", r"\1", text)
