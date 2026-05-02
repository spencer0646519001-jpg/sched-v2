from __future__ import annotations

import sys
from pathlib import Path


def _add_repo_root_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)


_add_repo_root_to_path()

from app.evals.refine_intent_eval import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

