"""Validate RR output files with the project-local JSON Schemas."""

import argparse
import json
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError:
    raise SystemExit("Install requirements-dev.txt in the project .venv to validate schemas.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--schema", choices=["rr-result.schema.json", "zotero-manifest.schema.json"], default="rr-result.schema.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directories = [root / "schemas", root / "rr/schemas", root / "zotero/schemas"]
    schemas = {p.name: json.loads(p.read_text(encoding="utf-8"))
               for directory in directories for p in directory.glob("*.schema.json")}
    registry = Registry().with_resources((name, Resource.from_contents(schema)) for name, schema in schemas.items())
    schema = schemas[args.schema]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    failures = 0
    for path in args.files:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        errors = list(validator.iter_errors(data))
        if errors:
            failures += 1
            for error in errors:
                print(f"FAIL {path}: {list(error.absolute_path)}: {error.message}")
        else:
            if "coverage" in data:
                print(f"PASS {path}: {data['status']}; {data['coverage']['raw_count']} rows; {data['coverage']['unique_count']} unique")
            else:
                print(f"PASS {path}: {data['counts']}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
