"""Guards the production compose file: local storage must point at the volume, or every redeploy deletes the posts."""

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class DeployStorageTests(SimpleTestCase):
    def setUp(self):
        self.compose = (ROOT / "deploy" / "docker-compose.yml").read_text()

    def test_local_storage_path_defaults_to_the_volume_mount(self):
        mount = re.search(r"-\s+storage:(/\S+)", self.compose).group(1)
        default = re.search(r"LOCAL_STORAGE_PATH:\s*\$\{LOCAL_STORAGE_PATH:-([^}]+)\}", self.compose).group(1)
        self.assertEqual(default, mount)

    def test_the_image_default_matches_the_volume_mount_too(self):
        mount = re.search(r"-\s+storage:(/\S+)", self.compose).group(1)
        self.assertIn(f"LOCAL_STORAGE_PATH={mount}", (ROOT / "Dockerfile").read_text())
