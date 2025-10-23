# update_checker.py

import os
import threading
from PyQt5.QtCore import QObject, pyqtSignal

class UpdateChecker(QObject):
    """
    Checks for new releases of HaasoscopePro on GitHub.
    Emits a signal when a newer version is available.
    """
    update_available = pyqtSignal(str, str, str)  # (current_version, latest_version, release_url)

    def __init__(self, current_version, ignore_file=".haasoscope_update_ignore"):
        super().__init__()
        self.current_version = str(current_version)
        self.ignore_file = ignore_file

    def check_for_updates(self):
        """Check for updates in a background thread (non-blocking)"""
        thread = threading.Thread(target=self._check_updates_thread, daemon=True)
        thread.start()

    def _check_updates_thread(self):
        """Background thread that performs the actual update check"""
        try:
            # Try to import requests - if not available, silently skip
            try:
                import requests
            except ImportError:
                print("Update check skipped: 'requests' module not installed. Do \"pip install requests\".")
                return

            url = "https://api.github.com/repos/drandyhaas/HaasoscopePro/releases/latest"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get('tag_name', '').replace('-beta', '')
                release_url = data.get('html_url', 'https://github.com/drandyhaas/HaasoscopePro/releases')
                print("Found latest version on github:",latest_tag)
                if self._is_newer_version(latest_tag) and not self._is_version_ignored(latest_tag):
                    self.update_available.emit(self.current_version, latest_tag, release_url)
        except Exception as e:
            # Silent fail - don't interrupt startup for update check failures
            print(f"Update check failed (non-critical): {e}")

    def _is_newer_version(self, latest_tag):
        """
        Compare version strings to determine if latest is newer than current.
        Handles versions like "31.06" properly.
        """
        try:
            # Try using packaging library for robust comparison
            try:
                from packaging import version
                return version.parse(latest_tag) > version.parse(self.current_version)
            except ImportError:
                # Fallback to simple float comparison if packaging not available
                return float(latest_tag) > float(self.current_version)
        except Exception:
            # If comparison fails, assume no update to avoid false positives
            return False

    def _is_version_ignored(self, version):
        """
        Check if a specific version has been ignored by the user.
        Returns True if the version is in the ignore file.
        """
        if not os.path.exists(self.ignore_file):
            return False

        try:
            with open(self.ignore_file, 'r') as f:
                ignored_versions = [line.strip() for line in f.readlines()]
                return version in ignored_versions
        except Exception as e:
            print(f"Error reading ignore file: {e}")
            return False

    def ignore_version(self, version):
        """
        Add a version to the ignore list.
        This version will not trigger update notifications in the future.
        """
        try:
            # Read existing ignored versions
            ignored_versions = []
            if os.path.exists(self.ignore_file):
                with open(self.ignore_file, 'r') as f:
                    ignored_versions = [line.strip() for line in f.readlines()]

            # Add new version if not already there
            if version not in ignored_versions:
                ignored_versions.append(version)
                with open(self.ignore_file, 'w') as f:
                    f.write('\n'.join(ignored_versions) + '\n')
                print(f"Version {version} added to ignore list")
        except Exception as e:
            print(f"Error saving ignored version: {e}")
