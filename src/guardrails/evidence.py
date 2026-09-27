"""Remove explicit classifier commands from a model's evidence view only."""

import re


_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_COMMAND_START = re.compile(r"^(?:SYSTEM OVERRIDE:\s*)?(?:ignore|return|classify|label|declare)\b", re.I)
_LABEL_DIRECTIVE = re.compile(r"\b(?:return|classify|label|declare)\b.*\b(?:supported|unsupported|contradictory)\b", re.I)


def factual_evidence_view(text: str) -> str:
    """Omit standalone labeling directives, retaining source facts and receipts.

    This deliberately narrow rule addresses observed classifier manipulation,
    not arbitrary prompt injection. Descriptions of code behavior and ordinary
    technical instructions are preserved. The original source is never edited.
    """
    sentences = _SENTENCES.split(text)
    kept = [sentence for sentence in sentences
            if not (_COMMAND_START.search(sentence.strip()) and _LABEL_DIRECTIVE.search(sentence))]
    return text if len(kept) == len(sentences) else " ".join(kept)
