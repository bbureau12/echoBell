import subprocess
import sys

# Run test script in subprocess to avoid import conflicts
result = subprocess.run(
    [sys.executable, "tests/test_url_photo_download.py"],
    capture_output=True,
    text=True,
    cwd="D:/Projects/echoBell/echoBell"
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)

sys.exit(result.returncode)
