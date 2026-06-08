import sys
import traceback
from pathlib import Path

import click

from agentman.app import AgentManApp
from agentman.tmux import Tmux, relaunch_in_tmux


CRASH_LOG = Path.home() / ".local" / "share" / "agentman" / "crash.log"


def _run_app(has_workspace: bool) -> None:
    try:
        AgentManApp(has_workspace=has_workspace).run()
    except Exception:
        CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
        CRASH_LOG.write_text(traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)


@click.command()
@click.option("--inner", is_flag=True, hidden=True,
              help="Run the TUI inside the prepared tmux layout.")
@click.option("--clean", is_flag=True,
              help="Kill any existing agentman session first, then start fresh.")
@click.option("--kill", "kill_only", is_flag=True,
              help="Kill the existing agentman session and exit (don't start).")
def cli(inner: bool, clean: bool, kill_only: bool) -> None:
    """agentman — manage Claude Code sessions across projects."""
    if inner:
        _run_app(has_workspace=True)
        return

    tmux = Tmux()

    if kill_only:
        if tmux.kill_session():
            click.echo("Killed the agentman session.")
        else:
            click.echo("No agentman session running.")
        return

    if clean:
        if tmux.kill_session():
            click.echo("Killed the old agentman session.")

    if Tmux.inside():
        # Already inside some other tmux — run inline with the suspend fallback.
        _run_app(has_workspace=False)
        return

    # Fresh terminal: build the two-pane layout and attach to it.
    relaunch_in_tmux()
