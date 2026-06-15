"""Enable `python -m penpine` (delegates to the CLI)."""
from penpine.cli.main import main

raise SystemExit(main())
