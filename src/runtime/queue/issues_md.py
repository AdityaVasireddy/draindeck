"""Issues.md parser (doc 09 §1, ADR-16). PURE: text → list[IssueSpec], no I/O
and no event emission (main.py owns reading the file and emitting IssueCreated).

Format (explicit stable ids — not positional, not content-hashed, so an issue's
identity is stable across edits):

    ## <id>: <title>
    <body lines...>
    Depends-On: id1, id2            (optional, anywhere in the body)
    ### Acceptance                  (optional subsection)
    - criterion one
    - criterion two

``<id>`` matches ``[A-Za-z0-9][A-Za-z0-9_-]*``. A body runs until the next
``## `` heading. Malformed input — a ``## `` heading not of the form
``id: title``, or a duplicate id — ABORTS (raises ``IssuesParseError``) rather
than silently dropping a work item; that matches the config-loader's fail-loud
posture. Selection order downstream is file order (first heading first), so runs
are deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^##\s+(?P<rest>.+?)\s*$")
_ID_TITLE = re.compile(r"^(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*(?P<title>.+?)\s*$")
_DEPENDS = re.compile(r"^Depends-On\s*:\s*(?P<deps>.*)$", re.IGNORECASE)
_ACCEPT_HEADING = re.compile(r"^###\s+Acceptance\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")


class IssuesParseError(ValueError):
    """The issues file is malformed. Startup aborts rather than dropping work."""


@dataclass
class IssueSpec:
    id: str
    title: str
    body: str = ""
    depends_on: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)


def parse(text: str) -> list[IssueSpec]:
    specs: list[IssueSpec] = []
    seen: set[str] = set()
    cur: IssueSpec | None = None
    body: list[str] = []
    in_acceptance = False

    def _flush() -> None:
        nonlocal cur, body, in_acceptance
        if cur is not None:
            cur.body = "\n".join(body).strip()
            specs.append(cur)
        cur, body, in_acceptance = None, [], False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        m = _HEADING.match(raw)
        if m:
            _flush()
            idm = _ID_TITLE.match(m.group("rest"))
            if not idm:
                raise IssuesParseError(
                    f"line {lineno}: heading '## {m.group('rest')}' is not of the "
                    f"form '## <id>: <title>'"
                )
            iid = idm.group("id")
            if iid in seen:
                raise IssuesParseError(f"line {lineno}: duplicate issue id {iid!r}")
            seen.add(iid)
            cur = IssueSpec(id=iid, title=idm.group("title"))
            continue

        if cur is None:
            continue  # preamble before the first issue heading is ignored

        if _ACCEPT_HEADING.match(raw):
            in_acceptance = True
            continue
        dep = _DEPENDS.match(raw.strip())
        if dep:
            cur.depends_on = [d.strip() for d in dep.group("deps").split(",") if d.strip()]
            continue
        if in_acceptance:
            b = _BULLET.match(raw.strip())
            if b:
                cur.acceptance_criteria.append(b.group("text"))
                continue
            # a non-bullet, non-blank line ends the acceptance subsection
            if raw.strip():
                in_acceptance = False
        body.append(raw)

    _flush()
    return specs
