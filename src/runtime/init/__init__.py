"""`draindeck init` — plug-and-play onboarding (doc 16, Issue A only).

Stack-awareness lives entirely here, in a detection table and the
command strings it proposes; the engine stays a stack-blind command
runner (doc 16 §1). This package never touches `Config`/`ValidationCfg`,
the event log, recovery, or the engine wrapper.
"""
from .command import InitAbort, cmd_init
from .detect import (
    CommandProposal,
    DetectionRow,
    build_command,
    detect_stacks,
    enumerate_js_files,
    resolve_interpreter,
)
from .generate import render_config, write_config

__all__ = [
    "CommandProposal",
    "DetectionRow",
    "InitAbort",
    "build_command",
    "cmd_init",
    "detect_stacks",
    "enumerate_js_files",
    "render_config",
    "resolve_interpreter",
    "write_config",
]
