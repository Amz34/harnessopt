"""Non-destructive compaction for agent instruction, skill, and memory files."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

from harnessopt.scanner import BULLET_RE, estimate_tokens, scan_workspace

HTML_COMMENT_RE = re.compile(r"<!--(?!\s*claim-policy:)[\s\S]*?-->")


@dataclass
class CompactionResult:
    path: str
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    duplicates_removed: int
    changed: bool

    def to_dict(self) -> dict[str, int | str | bool]:
        return asdict(self)


def compact_markdown(text: str) -> tuple[str, int]:
    """Strip non-directive HTML comments, collapse blank-line runs, and deduplicate bullets."""
    # Remove decorative HTML comments outside code fences by splitting on fenced blocks
    parts = re.split(r"(```[\s\S]*?```)", text)
    for idx in range(0, len(parts), 2):
        parts[idx] = HTML_COMMENT_RE.sub("", parts[idx])
    cleaned = "".join(parts)

    out_lines: list[str] = []
    seen_bullets: set[str] = set()
    duplicates = 0
    blank_run = 0
    in_fence = False

    for raw_line in cleaned.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            blank_run = 0
            out_lines.append(line)
            continue

        if in_fence:
            out_lines.append(raw_line)
            continue

        if not line:
            blank_run += 1
            if blank_run <= 1 and out_lines:
                out_lines.append("")
            continue

        blank_run = 0
        m = BULLET_RE.match(line)
        if m:
            norm = re.sub(r"\s+", " ", m.group(1).strip()).lower()
            if len(norm) >= 12:
                if norm in seen_bullets:
                    duplicates += 1
                    continue
                seen_bullets.add(norm)

        out_lines.append(line)

    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    result = "\n".join(out_lines) + ("\n" if text.endswith("\n") or out_lines else "")
    return result, duplicates


def compact_workspace(target: str | Path, dry_run: bool = False) -> list[CompactionResult]:
    """Compact markdown harness files in target workspace and return per-file metrics."""
    root = Path(target).resolve()
    base = root.parent if root.is_file() else root
    artefacts = scan_workspace(root)
    results: list[CompactionResult] = []

    for item in artefacts:
        if item.kind == "mcp":
            continue
        fpath = base / item.path
        original = fpath.read_text(encoding="utf-8", errors="replace")
        compacted, dups = compact_markdown(original)
        before = estimate_tokens(original)
        after = estimate_tokens(compacted)
        changed = compacted != original
        if changed and not dry_run:
            fpath.write_text(compacted, encoding="utf-8")
        results.append(
            CompactionResult(
                path=item.path,
                tokens_before=before,
                tokens_after=after,
                tokens_saved=max(0, before - after),
                duplicates_removed=dups,
                changed=changed,
            )
        )
    return results
