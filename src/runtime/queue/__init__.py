"""Local canonical queue (ADR-16). v1: a one-shot Issues.md parser that feeds
IssueCreated facts into the log. The local queue is authoritative; external
trackers (later) are one-way ingestion sources only."""
from .issues_md import IssueSpec, IssuesParseError, parse

__all__ = ["parse", "IssueSpec", "IssuesParseError"]
