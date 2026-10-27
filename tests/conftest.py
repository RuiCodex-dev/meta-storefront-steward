import os
import tempfile

# Tests never touch the real data folder, the real keys or the real pseudonym secret.
_tmp = tempfile.mkdtemp(prefix="steward-test-")
os.environ.setdefault("STEWARD_DATA", _tmp)
os.environ.setdefault("STEWARD_DB", os.path.join(_tmp, "test.db"))
os.environ.setdefault("STEWARD_KEYS", os.path.join(_tmp, "keys"))
os.environ.setdefault("STEWARD_TEST_PSEUDONYM_KEY", "test-only-not-a-secret")
