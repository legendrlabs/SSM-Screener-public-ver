"""Run the bundled SSM CLI from an installed skill or any task directory."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {'scan', 'check'}:
        defaults = ['--config', str(ROOT / 'config/default.json'),
                    '--overrides', str(ROOT / 'config/overrides.json')]
        if args[0] == 'scan':
            defaults += ['--watchlist', str(ROOT / 'config/watchlist.csv')]
        # User arguments follow defaults so explicit paths retain precedence.
        args = [args[0], *defaults, *args[1:]]
    sys.path.insert(0, str(ROOT))
    from ssm.cli import main as cli_main
    original = sys.argv
    try:
        sys.argv = [str(Path(__file__)), *args]
        return cli_main()
    finally:
        sys.argv = original


if __name__ == '__main__':
    main()
