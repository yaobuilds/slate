"""Point the server's private files at a throwaway folder for this test run."""

import atexit
import os
import shutil
import tempfile


def install(server) -> None:
    # One folder for the whole process. A later test file reuses it.
    if not os.environ.get("SLATE_STATE_DIR"):
        folder = tempfile.mkdtemp(prefix="slate-test-")
        os.environ["SLATE_STATE_DIR"] = folder
        atexit.register(shutil.rmtree, folder, True)
    server.use_state_dir(os.environ["SLATE_STATE_DIR"])
