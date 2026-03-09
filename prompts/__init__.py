"""Prompt loader and LLM output utilities."""

import os

_DIR = os.path.dirname(__file__)


def load_prompt(name):
    """Load a prompt file from the prompts/ directory by name (without .txt extension)."""
    path = os.path.join(_DIR, f"{name}.txt")
    with open(path, "r") as f:
        return f.read()


def strip_think(text):
    """Strip <think>...</think> blocks from LLM output, returning only the spoken content."""
    if "</think>" in text:
        return text.rsplit("</think>", 1)[-1].strip()
    if text.lstrip().startswith("<think>"):
        return ""
    return text
