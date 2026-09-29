"""Build the compact U.S. place-name dataset used by location search suggestions."""

import csv
import json
from pathlib import Path
import sys


PLACE_SUFFIXES = (
    " borough",
    " census designated place",
    " city and borough",
    " city",
    " consolidated government",
    " municipality",
    " town",
    " village",
    " CDP",
)


def clean_place_name(name):
    cleaned_name = name.strip()

    for suffix in PLACE_SUFFIXES:
        if cleaned_name.lower().endswith(suffix.lower()):
            return cleaned_name[: -len(suffix)].strip()

    return cleaned_name


# Emit only the fields required by browser-side nearest-place matching.
def build_place_index(source_path, destination_path):
    places = []

    with source_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter="|")

        for row in reader:
            places.append([
                row["USPS"],
                clean_place_name(row["NAME"]),
                round(float(row["INTPTLAT"]), 5),
                round(float(row["INTPTLONG"]), 5),
            ])

    payload = {
        "source": "U.S. Census Bureau 2025 Gazetteer Places",
        "year": 2025,
        "places": places,
    }
    destination_path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python build_us_places.py SOURCE.txt DESTINATION.json"
        )

    build_place_index(Path(sys.argv[1]), Path(sys.argv[2]))
