"""Unit tests for harnessopt."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

from harnessopt.auditor import audit_artefacts
from harnessopt.cli import main
from harnessopt.optimizer import compact_markdown, compact_workspace
from harnessopt.scanner import classify_path, estimate_tokens, scan_workspace


class TestHarnessOpt(unittest.TestCase):
    def test_estimate_tokens_monotonic(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)
        short = estimate_tokens("Use standard library only.")
        longer = estimate_tokens("Use standard library only. " * 20)
        self.assertGreater(short, 0)
        self.assertGreater(longer, short)

    def test_classify_path_layers(self) -> None:
        self.assertEqual(classify_path(Path("CLAUDE.md")), "instructions")
        self.assertEqual(classify_path(Path("AGENTS.md")), "instructions")
        self.assertEqual(classify_path(Path(".cursorrules")), "instructions")
        self.assertEqual(classify_path(Path("MEMORY.md")), "memory")
        self.assertEqual(classify_path(Path("skills/deploy/SKILL.md")), "skill")
        self.assertEqual(classify_path(Path(".mcp.json")), "mcp")
        self.assertIsNone(classify_path(Path("src/app.py")))

    def test_scan_and_audit_clean_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "CLAUDE.md").write_text(
                "# Workspace Rules\n\n"
                "- Run unit tests before every commit using `./src/main.py`.\n"
                "- Prefer deterministic standard-library modules over external packages.\n",
                encoding="utf-8",
            )
            (root / ".mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "filesystem": {
                                "command": "npx",
                                "args": ["-y", "@modelcontextprotocol/server-filesystem@1.0.2", "./src"],
                                "env": {"API_TOKEN": "${API_TOKEN}"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            artefacts = scan_workspace(root)
            self.assertEqual(len(artefacts), 2)
            report = audit_artefacts(artefacts, root=root)
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["readiness_score"], 100)

    def test_audit_flags_mcp_and_instruction_defects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text(
                "# Rules\n\n"
                "- Always validate JSON schemas before writing output files.\n"
                "- Reference `./missing/config.yaml` when initializing the worker.\n",
                encoding="utf-8",
            )
            (root / "MEMORY.md").write_text(
                "# Memory\n\n"
                "- Always validate JSON schemas before writing output files.\n",
                encoding="utf-8",
            )
            # Construct a synthetic credential string dynamically so static scanners do not flag source
            fake_secret = "sk-" + ("a1B2" * 6)
            (root / ".mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "raw_shell": {
                                "command": "/bin/bash",
                                "args": ["-c", "echo ready"],
                            },
                            "unpinned_fs": {
                                "command": "npx",
                                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"],
                                "env": {"OPENAI_API_KEY": fake_secret},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            artefacts = scan_workspace(root)
            report = audit_artefacts(artefacts, root=root, max_file_tokens=10, total_budget=20)
            rules = {f["rule"] for f in report["findings"]}
            self.assertIn("unrestricted_shell_server", rules)
            self.assertIn("unpinned_mcp_package", rules)
            self.assertIn("root_filesystem_scope", rules)
            self.assertIn("inline_secret_in_env", rules)
            self.assertIn("duplicate_directive", rules)
            self.assertIn("dead_path_reference", rules)
            self.assertIn("oversized_harness_file", rules)
            self.assertIn("context_budget_exceeded", rules)
            self.assertLess(report["readiness_score"], 50)

    def test_compact_markdown_preserves_fences_and_deduplicates(self) -> None:
        raw = (
            "<!-- claim-policy: verified -->\n"
            "# Agent Guide\n\n\n\n"
            "<!-- decorative note that wastes context tokens -->\n"
            "- Keep every CLI command deterministic and non-interactive.\n"
            "- Keep every CLI command deterministic and non-interactive.\n"
            "- Verify exit codes before reporting completion.\n\n"
            "```bash\n"
            "# Inside code fence duplicate lines must stay untouched\n"
            "- Keep every CLI command deterministic and non-interactive.\n"
            "\n\n\n"
            "```\n"
        )
        compacted, dups = compact_markdown(raw)
        self.assertEqual(dups, 1)
        self.assertIn("<!-- claim-policy: verified -->", compacted)
        self.assertNotIn("decorative note", compacted)
        self.assertEqual(
            compacted.count("- Keep every CLI command deterministic and non-interactive."),
            2,  # once in prose, once inside code fence
        )

    def test_cli_audit_and_compact_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md_path = root / "AGENTS.md"
            md_path.write_text(
                "# Instructions\n\n\n"
                "<!-- redundant comment -->\n"
                "- Write unit tests for every new parser module.\n"
                "- Write unit tests for every new parser module.\n",
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["audit", str(root), "--json"])
            self.assertEqual(rc, 0)
            audit_data = json.loads(buf.getvalue())
            self.assertEqual(audit_data["artefact_count"], 1)

            buf_compact = io.StringIO()
            with redirect_stdout(buf_compact):
                rc2 = main(["compact", str(root), "--json"])
            self.assertEqual(rc2, 0)
            compact_data = json.loads(buf_compact.getvalue())
            self.assertEqual(compact_data["files_changed"], 1)
            self.assertGreaterEqual(compact_data["tokens_saved"], 1)

            # Second run should report no further changes
            second = compact_workspace(root, dry_run=True)
            self.assertFalse(second[0].changed)


if __name__ == "__main__":
    unittest.main()
