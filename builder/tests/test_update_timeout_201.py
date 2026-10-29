"""Guard the GitHub timeout regression on slow work/home connections."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updates


class UpdateTimeoutTests(unittest.TestCase):
    def test_manifest_has_twenty_second_timeout(self):
        payload = json.dumps({
            "version": "2.0.1",
            "package_url": "https://github.com/example/update.zip",
            "sha256": "a" * 64,
        }).encode("utf-8")
        calls = []

        def open_mock(request, *, timeout):
            calls.append(timeout)
            return io.BytesIO(payload)

        with patch.object(updates.urllib.request, "urlopen", side_effect=open_mock):
            manifest = updates.fetch_manifest("https://raw.githubusercontent.com/example/latest.json")
        self.assertEqual(calls, [20.0])
        self.assertEqual(manifest["version"], "2.0.1")

    def test_package_download_has_ninety_second_timeout(self):
        data = b"test-only-package"
        sha = hashlib.sha256(data).hexdigest()
        calls = []

        def open_mock(request, *, timeout):
            calls.append(timeout)
            return io.BytesIO(data)

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates.tempfile, "gettempdir", return_value=folder), \
                 patch.object(updates.urllib.request, "urlopen", side_effect=open_mock):
                result = updates.download_package({
                    "version": "2.0.1",
                    "package_url": "https://github.com/example/update.zip",
                    "sha256": sha,
                })
                self.assertEqual(Path(result).read_bytes(), data)
        self.assertEqual(calls, [90.0])


if __name__ == "__main__":
    unittest.main()
