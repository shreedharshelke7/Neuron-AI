"""Neuron AI application entry point."""

import sys
from app.desktop.shell import run_desktop_shell


def main() -> int:
    """Launch the Neuron AI desktop shell application."""
    return run_desktop_shell(sys.argv)


if __name__ == "__main__":
    sys.exit(main())