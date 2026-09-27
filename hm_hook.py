"""Entry script for Bob hooks: `python hm_hook.py` (reads the hook payload on stdin)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hallmonitor.hook import main  # noqa: E402
from hallmonitor.jev import load_key_from_user_env  # noqa: E402

load_key_from_user_env()
main()
