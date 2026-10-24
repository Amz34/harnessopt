"""Workspace scanner for AI coding-agent harness artefacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".tox"}

INSTRUCTION_NAMES = {
    "claude.md",
    "agents.md",
    ".cursorrules",
    ".windsurfrules",
    "copilot-instructions.md",
    "conventions.md",
}

MEMORY_NAMES = {
    "memory.md",
    "user.md",
    "instincts.md",
    "lessons.md",
}

MCP_CONFIG_NAMES = {
    "mcp.json",
    ".mcp.json",
    "claude_desktop_config.json",
    "mcp_config.json",
}

HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate for English/code mixed text (~4 chars per token)."""
    if not text:
        return 0
    words = len(re.findall(r"\S+", text))
    chars_est = (len(text) + 3) // 4
    return max(words, chars_est)


@dataclass
class ArtefactMetrics:
    path: str
    kind: str  # instructions | skill | memory | mcp
    bytes: int
    lines: int
    estimated_tokens: int
    headings: int = 0
    bullets: list[str] = field(default_factory=list)
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bullet_count"] = len(self.bullets)
        del data["bullets"]
        del data["mcp_servers"]
        if self.kind == "mcp":
            data["mcp_server_names"] = sorted(self.mcp_servers.keys())
        return data


def classify_path(rel_path: Path) -> str | None:
    """Return the harness layer for a relative path, or None if unrelated."""
    name_lower = rel_path.name.lower()
    parts_lower = [p.lower() for p in rel_path.parts]

    if name_lower in MCP_CONFIG_NAMES or (
        name_lower.endswith(".json") and "mcp" in parts_lower
    ):
        return "mcp"
    if name_lower == "skill.md" or (
        name_lower.endswith(".md") and ("skills" in parts_lower or "commands" in parts_lower)
    ):
        return "skill"
    if name_lower in MEMORY_NAMES or (
        name_lower.endswith(".md") and ("memory" in parts_lower or "memories" in parts_lower)
    ):
        return "memory"
    if name_lower in INSTRUCTION_NAMES or (
        name_lower.endswith(".md") and ".cursor" in parts_lower
    ):
        return "instructions"
    return None


def analyze_artefact(root: Path, file_path: Path, kind: str) -> ArtefactMetrics:
    rel = str(file_path.relative_to(root)) if file_path != root else file_path.name
    raw = file_path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    tokens = estimate_tokens(raw)

    if kind == "mcp":
        servers: dict[str, Any] = {}
        err: str | None = None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                raw_servers = parsed.get("mcpServers") or parsed.get("servers") or {}
                if isinstance(raw_servers, dict):
                    servers = raw_servers
        except json.JSONDecodeError as exc:
            err = f"Invalid JSON: {exc.msg} (line {exc.lineno})"
        return ArtefactMetrics(
            path=rel,
            kind=kind,
            bytes=len(raw.encode("utf-8")),
            lines=len(lines),
            estimated_tokens=tokens,
            mcp_servers=servers,
            parse_error=err,
        )

    headings = 0
    bullets: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if HEADING_RE.match(line):
            headings += 1
        m = BULLET_RE.match(line)
        if m:
            norm = re.sub(r"\s+", " ", m.group(1).strip())
            if len(norm) >= 12:
                bullets.append(norm)

    return ArtefactMetrics(
        path=rel,
        kind=kind,
        bytes=len(raw.encode("utf-8")),
        lines=len(lines),
        estimated_tokens=tokens,
        headings=headings,
        bullets=bullets,
    )


def scan_workspace(target: str | Path) -> list[ArtefactMetrics]:
    """Walk target path and collect harness artefacts in deterministic path order."""
    root = Path(target).resolve()
    if root.is_file():
        kind = classify_path(Path(root.name)) or (
            "mcp" if root.suffix.lower() == ".json" else "instructions"
        )
        return [analyze_artefact(root.parent, root, kind)]

    found: list[ArtefactMetrics] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(root)
            kind = classify_path(rel)
            if kind is not None:
                found.append(analyze_artefact(root, fpath, kind))
    return found
