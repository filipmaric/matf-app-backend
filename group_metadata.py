# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Infer study metadata encoded in timetable group names."""

import re


_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ж": "ž",
        "з": "z",
        "и": "i",
        "ј": "j",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "č",
        "ш": "š",
    }
)


def infer_group_metadata(name):
    """Return ``(study_program, module, accreditation, study_year)``.

    The final letters in a group name identify a timetable stream or subgroup,
    so they are deliberately ignored.  Names which do not follow the known
    undergraduate/master group conventions return three ``None`` values.
    """
    normalized = str(name or "").strip().lower().translate(_CYRILLIC_TO_LATIN)
    match = re.fullmatch(r"([1-5])(.*)", normalized)
    if not match:
        return None, None, None, None

    year = int(match.group(1))
    body = match.group(2)
    if not body:
        return None, None, None, None

    # The first-year M groups have no module split yet.
    if year == 1 and body.startswith("o"):
        return "M", None, 2022, year

    # The fifth-year I groups are an exceptional 2019 accreditation.
    if year == 5 and re.fullmatch(r"i[12]?", body):
        return "I", None, 2019, year

    if body.startswith("i"):
        if "15" in body[1:]:
            accreditation = 2015
        elif year == 4 or body[1:].startswith("17"):
            accreditation = 2017
        else:
            accreditation = 2024
        return "I", None, accreditation, year

    if body.startswith("a"):
        module = body[1] if len(body) > 1 and body[1] in "fi" else "f"
        accreditation = 2015 if "15" in body[1:] else 2022
        return "A", module.upper(), accreditation, year

    if body[0] in "mrspl":
        accreditation = 2015 if "15" in body[1:] else 2022
        return "M", body[0].upper(), accreditation, year

    return None, None, None, None
