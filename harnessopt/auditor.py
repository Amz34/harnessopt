"""Security, hygiene, and context-budget checks for agent harness artefacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from harnessopt.scanner import ArtefactMetrics

SECRET_VALUE_RE = re.compile(
    r"^(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[A-Za-z0-9-]{16,}|AKIA[0-9A-Z]{16})$"
)
ENV_REF_RE = re.compile(r"^(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|env:[A-Za-z_][A-Za-z0-9_]*)$")
SHELL_BINARIES = {"bash", "sh", "zsh", "powershell", "cmd", "cmd.exe"}
BACKTICK_PATH_RE = re.compile(r"`(\./[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")


@dataclass
class Finding:
    rule: str
    severity: str  # HIGH | MEDIUM | LOW
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _check_mcp_artefact(item: ArtefactMetrics) -> list[Finding]:
    findings: list[Finding] = []
    if item.parse_error:
        findings.append(
            Finding(
                rule="invalid_mcp_json",
                severity="HIGH",
                path=item.path,
                message=item.parse_error,
            )
        )
        return findings

    for srv_name, cfg in sorted(item.mcp_servers.items()):
        if not isinstance(cfg, dict):
            continue
        cmd = str(cfg.get("command") or "").strip()
        args = [str(a) for a in (cfg.get("args") or []) if isinstance(a, (str, int, float))]
        env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}

        base_cmd = Path(cmd).name.lower() if cmd else ""
        if base_cmd in SHELL_BINARIES and any(a in {"-c", "/c"} for a in args):
            findings.append(
                Finding(
                    rule="unrestricted_shell_server",
                    severity="HIGH",
                    path=item.path,
                    message=f"MCP server '{srv_name}' invokes a raw shell ({base_cmd} -c) without a wrapper boundary.",
                )
            )

        if base_cmd in {"npx", "uvx", "bunx"}:
            pkg_tokens = [a for a in args if not a.startswith("-")]
            if pkg_tokens:
                pkg = pkg_tokens[0]
                # Scoped package @scope/name has one leading '@'; version pin adds another '@'
                at_count = pkg.count("@")
                pinned = (at_count >= 2) if pkg.startswith("@") else (at_count >= 1)
                if not pinned:
                    findings.append(
                        Finding(
                            rule="unpinned_mcp_package",
                            severity="MEDIUM",
                            path=item.path,
                            message=f"MCP server '{srv_name}' runs '{base_cmd} {pkg}' without an explicit version pin.",
                        )
                    )

        if "/" in args:
            findings.append(
                Finding(
                    rule="root_filesystem_scope",
                    severity="HIGH",
                    path=item.path,
                    message=f"MCP server '{srv_name}' grants root directory ('/') access in args.",
                )
            )

        for env_key, env_val in sorted(env.items()):
            sval = str(env_val).strip()
            if not sval or ENV_REF_RE.match(sval):
                continue
            if SECRET_VALUE_RE.match(sval) or (
                any(tok in env_key.upper() for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
                and len(sval) >= 12
            ):
                findings.append(
                    Finding(
                        rule="inline_secret_in_env",
                        severity="HIGH",
                        path=item.path,
                        message=f"MCP server '{srv_name}' embeds a literal credential in env.{env_key} instead of an environment variable reference.",
                    )
                )

    return findings


def audit_artefacts(
    artefacts: list[ArtefactMetrics],
    root: Path | None = None,
    max_file_tokens: int = 2000,
    total_budget: int = 8000,
) -> dict[str, Any]:
    """Run all deterministic checks across scanned artefacts and compute a readiness score."""
    findings: list[Finding] = []
    seen_bullets: dict[str, str] = {}
    layer_tokens = {"instructions": 0, "skill": 0, "memory": 0, "mcp": 0}

    for item in artefacts:
        layer_tokens[item.kind] = layer_tokens.get(item.kind, 0) + item.estimated_tokens

        if item.kind == "mcp":
            findings.extend(_check_mcp_artefact(item))
            continue

        if item.estimated_tokens > max_file_tokens:
            findings.append(
                Finding(
                    rule="oversized_harness_file",
                    severity="MEDIUM",
                    path=item.path,
                    message=f"{item.kind} file est. {item.estimated_tokens} tokens exceeds per-file threshold ({max_file_tokens}).",
                )
            )

        for bullet in item.bullets:
            key = bullet.lower()
            if key in seen_bullets:
                prev = seen_bullets[key]
                findings.append(
                    Finding(
                        rule="duplicate_directive",
                        severity="LOW",
                        path=item.path,
                        message=f"Directive repeated (first seen in {prev}): '{bullet[:70]}'",
                    )
                )
            else:
                seen_bullets[key] = item.path

        if root is not None and root.is_dir():
            fpath = root / item.path
            if fpath.is_file():
                raw = fpath.read_text(encoding="utf-8", errors="replace")
                for match in BACKTICK_PATH_RE.finditer(raw):
                    rel_ref = match.group(1)
                    candidate = (root / rel_ref).resolve()
                    if not candidate.exists():
                        findings.append(
                            Finding(
                                rule="dead_path_reference",
                                severity="MEDIUM",
                                path=item.path,
                                message=f"Referenced workspace path '{rel_ref}' does not exist.",
                            )
                        )

    total_tokens = sum(layer_tokens.values())
    if total_tokens > total_budget:
        findings.append(
            Finding(
                rule="context_budget_exceeded",
                severity="MEDIUM",
                path="<workspace>",
                message=f"Total harness footprint ({total_tokens} est. tokens) exceeds target budget ({total_budget}).",
            )
        )

    penalties = {"HIGH": 20, "MEDIUM": 8, "LOW": 3}
    deduction = sum(penalties.get(f.severity, 3) for f in findings)
    score = max(0, 100 - deduction)

    return {
        "artefact_count": len(artefacts),
        "total_estimated_tokens": total_tokens,
        "layer_tokens": layer_tokens,
        "readiness_score": score,
        "artefacts": [a.to_dict() for a in artefacts],
        "findings": [f.to_dict() for f in findings],
    }
