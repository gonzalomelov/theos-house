"""Seat profile from the maker's manual: the steps for a 3-point belt install without a base, the warnings
around them, the child limits, the handle position for the car and the level indicator.

Text only. The PDF is read on this machine with pdftotext (poppler) and only the extracted text is used,
so the brain never sees a page image. The manual itself stays outside the repo, the profile records its URL
and SHA-256 so anyone can fetch the same file from the maker and check it.

    python -m parenting_agent.carseat.manual MANUAL.pdf --seat "Joie i-Snug 2" --url URL > skills/carseat/joie-i-snug-2.json
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BELT_SECTION = re.compile(r"^Installation without base\b", re.I)
SECTION_END = re.compile(r"^(Use with Strollers|Installation with base|Care and Maintenance|Detaching|Handle Adjustment)\b"
                         r"|\bstrollers?\b", re.I)
STEP = re.compile(r"^(\d+)\.\s+(.*)")
FIGURE_REF = re.compile(r"(\s+\d+(\s*-\s*\d+)?(\s*&\s*\d+)*)+(\s+[A-Z].*)?$")
HEIGHT = re.compile(r"Child height\s*(\d+)\s*cm\s*-\s*(\d+)\s*cm", re.I)
WEIGHT = re.compile(r"Child weight\s*≤?\s*(\d+(?:\.\d+)?)\s*kg", re.I)
AGE = re.compile(r"Child age\s*[≤<]\s*(\d+)\s*months", re.I)
HANDLE_CAR = re.compile(r"Position\s*(\d)\s*-\s*Position for car", re.I)


def pdf_text(path, first=1, last=30):
    """English pages of the manual as plain text, extracted locally."""
    out = subprocess.run(["pdftotext", "-raw", "-f", str(first), "-l", str(last), str(path), "-"],
                         capture_output=True, text=True, check=True)
    return out.stdout


def _clean(text):
    text = re.sub(r"\s+", " ", text).strip()
    return FIGURE_REF.sub("", text).strip()


def belt_section(lines):
    """Lines of the English belt install section, from its header to the next section header."""
    start = next((i for i, line in enumerate(lines) if BELT_SECTION.match(line.strip())), None)
    if start is None:
        raise ValueError("no 'Installation without base' section in this manual text")
    end = next((i for i in range(start + 1, len(lines)) if SECTION_END.search(lines[i].strip())), len(lines))
    return lines[start + 1:end]


def parse_section(lines):
    """Numbered steps and '!' warnings. A step or warning runs on over the following lines until the next step
    or warning. Figure references, page numbers and 'see images' lines are dropped."""
    steps, warnings, current = [], [], None
    for raw in lines:
        line = raw.strip()
        if not line or line == "!" or re.fullmatch(r"[\d\s]+", line) or line.lower().startswith("see images"):
            continue
        m = STEP.match(line)
        if m:
            current = {"n": int(m.group(1)), "text": m.group(2)}
            if not any(s["n"] == current["n"] for s in steps):
                steps.append(current)
            else:
                current = None
            continue
        if line.startswith("!"):
            current = {"text": line.lstrip("! ").strip()}
            warnings.append(current)
            continue
        if current is not None:
            current["text"] += " " + line
    clean = lambda items: [_clean(i["text"]) for i in items]
    ordered = sorted(steps, key=lambda s: s["n"])
    return clean(ordered), clean(warnings)


def limits(text):
    height = HEIGHT.search(text)
    weight = WEIGHT.search(text)
    age = AGE.search(text)
    return {"height_cm": [int(height.group(1)), int(height.group(2))] if height else None,
            "max_weight_kg": float(weight.group(1)) if weight else None,
            "max_age_months": int(age.group(1)) if age else None}


def profile_from_text(text, seat, url=None, sha256=None):
    lines = text.splitlines()
    steps, warnings = parse_section(belt_section(lines))
    handle = HANDLE_CAR.search(text)
    level = next((s for s in steps if re.search(r"level", s, re.I)), None)
    return {
        "seat": seat,
        "method": "vehicle 3-point belt, rear facing, no base",
        "manual": {"url": url, "sha256": sha256, "section": "Installation without base"},
        "limits": limits(text),
        "steps": steps,
        "warnings": warnings,
        "handle_car_position": int(handle.group(1)) if handle else None,
        "level_indicator": level,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manual", help="the maker's manual, PDF or extracted text")
    parser.add_argument("--seat", required=True)
    parser.add_argument("--url")
    parser.add_argument("--last-page", type=int, default=30, help="last page of the English part")
    args = parser.parse_args()
    path = Path(args.manual)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    text = pdf_text(path, last=args.last_page) if path.suffix.lower() == ".pdf" else path.read_text()
    json.dump(profile_from_text(text, args.seat, args.url, digest), sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
