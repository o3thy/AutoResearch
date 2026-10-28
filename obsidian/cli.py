"""Project-local entry point for the integrated ResearchVault tools."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .handoff import prepare_handoff, save_new
from .tools.config import configured_path, load_config

MODULE = Path(__file__).resolve().parent


def run_tool(relative, arguments, capture=False):
    environment = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run([sys.executable, str(MODULE / relative), *map(str, arguments)],
                            env=environment, capture_output=capture, text=True, encoding="utf-8")
    if capture:
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Upstream helper failed")
        return json.loads(result.stdout)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 3: Zotero → Fulltext → Analytical Notes → Knowledge")
    parser.add_argument("--config", type=Path, help="Local configuration; default: obsidian/config.toml or RESEARCHVAULT_CONFIG")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only environment checks")
    fetch = sub.add_parser("fetch", help="Read a specified Zotero parent and attachments without database writes")
    fetch.add_argument("--key", required=True)
    prepare = sub.add_parser("prepare", help="Verify attached stage-two records and create a new agent handoff JSON")
    prepare.add_argument("manifest", type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--vault-root", type=Path)
    prepare.add_argument("--limit", type=int)
    init = sub.add_parser("init", help="Explicitly initialize a chosen Vault; existing content is preserved")
    init.add_argument("--vault-root", required=True, type=Path)
    validate = sub.add_parser("validate", help="Run both read-only upstream validators")
    validate.add_argument("--vault-root", type=Path)
    convert = sub.add_parser("convert", help="Run the optional configured MinerU CLI on one specified PDF")
    convert.add_argument("--input", required=True, type=Path)
    convert.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    config_path = args.config or Path(os.environ.get("RESEARCHVAULT_CONFIG", MODULE / "config.toml"))
    config = load_config(config_path)
    config_args = ["--config", config_path]
    try:
        if args.command == "doctor":
            code = run_tool("tools/check_environment.py", config_args)
            for executable in ("pdfinfo", "pdftotext", "pdftoppm"):
                print(f"{'PASS' if shutil.which(executable) else 'WARN'}: optional Poppler {executable}: {shutil.which(executable) or 'not found'}")
            print("INFO: Analytical Note/Knowledge writing is performed by the seven agent Skills, not this CLI.")
            return code
        if args.command == "fetch":
            return run_tool("tools/zotero_readonly_fetch.py", ["--key", args.key, *config_args])
        if args.command == "init":
            return run_tool("tools/init_vault.py", ["--vault-root", args.vault_root, *config_args])
        if args.command == "convert":
            return run_tool("tools/run_mineru_production.py", ["--input", args.input, "--output", args.output, *config_args])
        vault = args.vault_root or configured_path("vault_root", config)
        if vault is None:
            raise ValueError("Set paths.vault_root in the local config or pass --vault-root")
        if args.command == "validate":
            links = run_tool("tools/validate_research_vault_literature_links.py", ["--vault", vault])
            knowledge = run_tool("skills/research-vault-knowledge-maintainer/scripts/validate_research_vault_knowledge.py", ["--vault", vault])
            return 1 if links or knowledge else 0
        if args.output.exists():
            raise ValueError("Output already exists; choose a new handoff path")
        data = prepare_handoff(args.manifest, vault,
                               lambda key: run_tool("tools/zotero_readonly_fetch.py", ["--key", key, *config_args], capture=True),
                               args.limit)
        save_new(args.output, data)
        print(json.dumps({"status": data["status"], "counts": data["counts"], "handoff": str(args.output.resolve()),
                          "vault_root": data["vault_root"], "next_skill": "research-vault-ingest-orchestrator"}, ensure_ascii=False, indent=2))
        return 0 if data["status"] in {"ready", "empty"} else 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
