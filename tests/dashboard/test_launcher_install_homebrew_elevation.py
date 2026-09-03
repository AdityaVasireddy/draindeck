"""RED test, ULTRA-REVIEW-001 finding 5: Homebrew elevation messaging must
correctly distinguish a `brew install <formula>` from the
`brew install --cask claude-code` invocation.

Root cause under test: `src/draindeck_dashboard/launcher_install.py`'s
`detect_missing_prerequisites` computes, per prerequisite:

    may_prompt_elevation=installer.package_manager != "brew" or name != "claude"

which is True for every brew item EXCEPT `claude`. That is exactly
backwards: Homebrew's core, well-documented design point is that
`brew install <formula>` (e.g. `ollama`, `git`) never needs sudo/elevation
-- that's the entire reason Homebrew exists as an alternative to
system package managers. `brew install --cask claude-code` is the one
Homebrew invocation here that can actually prompt for elevation. The
current logic flags every formula install as elevation-prompting and
marks the one cask install as the exception that is NOT -- the operator
sees exactly the wrong prerequisite manifest.

Planning-gate only (docs/32 review, ULTRA-REVIEW-001): no `src/` change here.
"""
from __future__ import annotations

from draindeck_dashboard import launcher_install


def test_homebrew_elevation_correctly_distinguishes_formula_from_cask():
    installer = launcher_install.PlatformInstaller(
        "darwin", "brew", "terminal sudo only after consent",
    )
    missing = launcher_install.detect_missing_prerequisites(
        installer=installer,
        git_present=False, claude_present=False, ollama_present=False,
        dashboard_deps_present=True,
    )
    by_name = {p.name: p for p in missing}
    assert set(by_name) == {"git", "claude", "ollama"}

    assert by_name["ollama"].may_prompt_elevation is False, (
        "RED (finding 5): `brew install ollama` is a Homebrew FORMULA install -- "
        "Homebrew's own design never requires sudo for this -- but the current "
        "code reports may_prompt_elevation=True for it."
    )
    assert by_name["git"].may_prompt_elevation is False, (
        "RED (finding 5): `brew install git` is a Homebrew FORMULA install and "
        "must not be reported as elevation-prompting either."
    )
    assert by_name["claude"].may_prompt_elevation is True, (
        "RED (finding 5): `brew install --cask claude-code` is the Homebrew CASK "
        "install here -- the one that may actually prompt for elevation -- but the "
        "current code reports may_prompt_elevation=False for it, exactly backwards "
        "from the formula installs above."
    )
