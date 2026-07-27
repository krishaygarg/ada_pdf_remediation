import os
import tempfile

# Force all temp files to be created within the workspace to comply with the sandbox
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_TMP = os.path.join(WORKSPACE_DIR, "tmp")

os.makedirs(LOCAL_TMP, exist_ok=True)
os.environ['TMPDIR'] = LOCAL_TMP
os.environ['TEMP'] = LOCAL_TMP
os.environ['TMP'] = LOCAL_TMP
tempfile.tempdir = LOCAL_TMP
