"""reset: start the store of a target afresh after its Wikibase was set up anew (requirement WC9).

After a reset of the server, the same Q and P numbers name other entities, and an ordinary sync would mix old and new
versions in one store. reset packs everything below the target's folder into a dated ZIP archive under
<data root>/_archives/<target>/, checks the archive file by file against the originals (size and CRC), and then moves
the old folder next to the archive. The tool never deletes: the old folder stays until a person removes it after
looking at the archive. The next sync writes a new store.

Because the step is rare and cannot be undone by the tool, it asks three times, and only in a terminal: confirm the
summary, solve a random sum, type the target name. There is no option that skips the questions, so neither a script
nor an agent can run it.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ARCHIVES = "_archives"   # below the data root; starts with "_", so it is never a target name


class NotInteractive(RuntimeError):
    """reset runs only in a terminal (no TTY: a script or an agent)."""


class NotConfirmed(RuntimeError):
    """One of the three questions was not answered as asked."""


class ArchiveMismatch(RuntimeError):
    """The archive does not match the files; the store stays where it is."""


@dataclass
class Plan:
    target: str
    root: Path
    archive: Path
    moved_to: Path
    files: list[Path] = field(default_factory=list)
    size: int = 0


def plan(data_root: Path, target: str, now: datetime | None = None) -> Plan:
    """What reset would do; reads only."""
    root = Path(data_root) / target
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    folder = Path(data_root) / ARCHIVES / target
    files = sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []
    return Plan(target=target, root=root, archive=folder / f"{target}_{stamp}.zip", moved_to=folder / f"{target}_{stamp}",
                files=files, size=sum(p.stat().st_size for p in files))


def confirm(p: Plan, ask=input, interactive=None, rng: random.Random | None = None, out=print) -> None:
    """Three questions; raises NotInteractive or NotConfirmed, returns only when all three were answered."""
    # input and output both in a terminal: on Windows the null device NUL reports isatty() on stdin, a pipe on
    # stdout does not, so a script or an agent is caught by the second check
    if not (interactive() if interactive else sys.stdin.isatty() and sys.stdout.isatty()):
        raise NotInteractive("reset asks three questions and runs only in a terminal; run it yourself")
    plain_ask = ask

    def ask(prompt: str) -> str:   # the end of the input counts as no
        try:
            return plain_ask(prompt)
        except EOFError:
            raise NotConfirmed("no answer") from None
    out(f"\nRESET of the store of {p.target!r}\n"
        f"  Store:    {p.root} ({len(p.files)} files, {p.size / 1_000_000:.1f} MB)\n"
        f"  Archive:  {p.archive}\n"
        f"  Then the old folder moves to {p.moved_to}; nothing is deleted.\n"
        f"Use this only when the Wikibase itself was set up anew.")
    if ask("1/3  Archive this store and start afresh? Type yes: ").strip().lower() != "yes":
        raise NotConfirmed("not confirmed")
    rng = rng or random.SystemRandom()
    a, b = rng.randint(12, 89), rng.randint(12, 89)
    if ask(f"2/3  Safety check: what is {a} + {b}? ").strip() != str(a + b):
        raise NotConfirmed("wrong sum")
    if ask(f"3/3  Type the name of the target ({p.target}) to confirm: ").strip() != p.target:
        raise NotConfirmed("name does not match")


def _crc(path: Path) -> int:
    crc = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            crc = zlib.crc32(chunk, crc)
    return crc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive(p: Plan, out=print) -> dict:
    """Packs, checks and moves the store. Writes a manifest next to the archive and returns it."""
    if p.archive.exists() or p.moved_to.exists():
        raise ArchiveMismatch(f"{p.archive.name} exists already; wait a second and run reset again.")
    p.archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p.archive, "x", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in p.files:
            zf.write(path, path.relative_to(p.root).as_posix())
    with zipfile.ZipFile(p.archive) as zf:
        if zf.testzip() is not None:
            raise ArchiveMismatch(f"{p.archive} is damaged; the store stays where it is.")
        infos = {i.filename: i for i in zf.infolist()}
    for path in p.files:
        info = infos.get(path.relative_to(p.root).as_posix())
        if info is None or info.file_size != path.stat().st_size or info.CRC != _crc(path):
            raise ArchiveMismatch(f"{path} differs from the archive; the store stays where it is.")
    if len(infos) != len(p.files):
        raise ArchiveMismatch("the archive holds other files than the store; the store stays where it is.")
    manifest = {"target": p.target, "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "store": str(p.root), "files": len(p.files), "bytes": p.size, "archive": p.archive.name,
                "archive_sha256": _sha256(p.archive), "old_folder": p.moved_to.name,
                "note": "The old folder can be removed by a person after checking the archive; the tool never deletes."}
    p.archive.with_suffix(".json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if p.root.exists():
        p.root.rename(p.moved_to)
    out(f"Archived {len(p.files)} files to {p.archive} (checked); old folder now {p.moved_to}.")
    return manifest
