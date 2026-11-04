"""Command-line interface for harnessopt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from harnessopt.auditor import audit_artefacts
from harnessopt.gate import get_template, list_templates, run_pipeline
from harnessopt.optimizer import compact_workspace
from harnessopt.scanner import scan_workspace

SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessopt",
        description="Audit and compact AI coding-agent harness configurations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Scan workspace harness files for bloat and security issues")
    p_audit.add_argument("path", nargs="?", default=".", help="Workspace directory or file to scan")
    p_audit.add_argument("--max-file-tokens", type=int, default=2000, help="Per-file token warning threshold")
    p_audit.add_argument("--budget", type=int, default=8000, help="Total workspace harness token budget")
    p_audit.add_argument(
        "--fail-on",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Exit non-zero if any finding meets or exceeds this severity",
    )
    p_audit.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")

    p_compact = sub.add_parser("compact", help="Deduplicate directives and trim noise in harness markdown files")
    p_compact.add_argument("path", nargs="?", default=".", help="Workspace directory or file to compact")
    p_compact.add_argument("--dry-run", action="store_true", help="Report savings without modifying files")
    p_compact.add_argument("--json", action="store_true", help="Emit JSON summary")

    p_template = sub.add_parser("template", help="Manage multi-agent graph templates (software-change, security-review, doc-sync)")
    p_template.add_argument("action", choices=["list", "show"], default="list", nargs="?", help="Action to perform")
    p_template.add_argument("--name", type=str, default="software-change", help="Template name to show")

    p_run = sub.add_parser("run", help="Execute an autonomous verification and review pipeline")
    p_run.add_argument("path", nargs="?", default=".", help="Workspace directory")
    p_run.add_argument("--template", type=str, default="software-change", help="Graph template to execute")
    p_run.add_argument("--dry-run", action="store_true", help="Simulate pipeline without executing commands")
    p_run.add_argument("--json", action="store_true", help="Emit JSON pipeline results")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    target_path = getattr(args, "path", ".")
    target = Path(target_path)
    if hasattr(args, "path") and not target.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 2

    if args.command == "audit":
        artefacts = scan_workspace(target)
        report = audit_artefacts(
            artefacts,
            root=target.resolve() if target.is_dir() else target.resolve().parent,
            max_file_tokens=args.max_file_tokens,
            total_budget=args.budget,
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(
                f"Harness Audit: {report['artefact_count']} artefact(s), "
                f"{report['total_estimated_tokens']} est. tokens, "
                f"readiness {report['readiness_score']}/100"
            )
            for item in report["artefacts"]:
                print(
                    f"  [{item['kind']}] {item['path']} "
                    f"({item['lines']} lines, ~{item['estimated_tokens']} tokens)"
                )
            if report["findings"]:
                print("\nFindings:")
                for f in report["findings"]:
                    print(f"  [{f['severity']}] {f['rule']} ({f['path']}): {f['message']}")
            else:
                print("\nFindings: none")

        if args.fail_on != "none":
            threshold = SEVERITY_RANK[args.fail_on.upper()]
            if any(SEVERITY_RANK.get(f["severity"], 0) >= threshold for f in report["findings"]):
                return 1
        return 0

    if args.command == "compact":
        results = compact_workspace(target, dry_run=args.dry_run)
        total_saved = sum(r.tokens_saved for r in results)
        changed_count = sum(1 for r in results if r.changed)
        payload = {
            "dry_run": args.dry_run,
            "files_scanned": len(results),
            "files_changed": changed_count,
            "tokens_saved": total_saved,
            "results": [r.to_dict() for r in results],
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            mode = "Dry-run compaction" if args.dry_run else "Compaction complete"
            print(f"{mode}: {changed_count}/{len(results)} file(s) updated, ~{total_saved} tokens saved")
            for r in results:
                status = "updated" if r.changed else "clean"
                print(
                    f"  {r.path}: {r.tokens_before} -> {r.tokens_after} tokens "
                    f"(-{r.tokens_saved}, {r.duplicates_removed} dup bullets) [{status}]"
                )
        return 0

    if args.command == "template":
        if args.action == "list":
            templates = list_templates()
            print("Available Meta-Harness Templates:")
            for name, meta in templates.items():
                print(f"  • {name}: {meta['description']}")
            return 0
        elif args.action == "show":
            tmpl = get_template(args.name)
            if not tmpl:
                print(f"error: unknown template '{args.name}'", file=sys.stderr)
                return 1
            print(json.dumps(tmpl, indent=2))
            return 0

    if args.command == "run":
        try:
            results = run_pipeline(
                template_name=args.template,
                workspace=target,
                dry_run=args.dry_run,
            )
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                status_icon = "✓" if results["success"] else "✗"
                print(f"[{status_icon}] Pipeline '{args.template}' executed on {target} ({results['status']})")
                for s in results["stages_run"]:
                    print(f"  • Stage '{s['stage']}': {s.get('status', 'done')}")
            return 0 if results["success"] else 1
        except Exception as e:
            print(f"error: pipeline execution failed: {e}", file=sys.stderr)
            return 1

    return 0
