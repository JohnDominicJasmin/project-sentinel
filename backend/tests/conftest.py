import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="sentinel-test-"), "test.db")
os.environ["TRIAGE"] = "rules"
os.environ["CAMERA_FEED"] = "off"
