"""GitHub release checking and Windows installer handoff."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.version import APP_VERSION, GITHUB_REPOSITORY, INSTALLER_ASSET_NAME


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    name: str
    installer_url: str


def _version_tuple(value: str) -> tuple[int, ...]:
    value = value.strip().lstrip("vV")
    parts = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts or [0])


class UpdateService:
    """Small standard-library client for the latest stable GitHub release."""

    api_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"

    @classmethod
    def check(cls, timeout: int = 4) -> ReleaseInfo | None:
        request = urllib.request.Request(
            cls.api_url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "CiteMind"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)

        if payload.get("draft") or payload.get("prerelease"):
            return None

        tag_name = str(payload.get("tag_name", "")).strip()
        if not tag_name or _version_tuple(tag_name) <= _version_tuple(APP_VERSION):
            return None

        for asset in payload.get("assets", []):
            if asset.get("name") == INSTALLER_ASSET_NAME and asset.get("browser_download_url"):
                return ReleaseInfo(
                    version=tag_name.lstrip("vV"),
                    name=str(payload.get("name") or tag_name),
                    installer_url=asset["browser_download_url"],
                )
        return None

    @staticmethod
    def download(release: ReleaseInfo, progress=None) -> Path:
        target = Path(tempfile.gettempdir()) / f"CiteMind-{release.version}-Setup.exe"
        request = urllib.request.Request(
            release.installer_url,
            headers={"User-Agent": "CiteMind"},
        )
        with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(min(100, int(downloaded * 100 / total)))
        return target

    @staticmethod
    def install_after_exit(installer_path: Path) -> None:
        application_path = Path(os.path.abspath(os.sys.executable))
        script_path = Path(tempfile.gettempdir()) / "CiteMind-update.cmd"
        script = "\n".join(
            [
                "@echo off",
                "timeout /t 2 /nobreak >nul",
                f'start /wait "" "{installer_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS',
                f'del /q "{installer_path}" >nul 2>&1',
                f'start "" "{application_path}"',
                'del /q "%~f0" >nul 2>&1',
            ]
        )
        script_path.write_text(script, encoding="ascii")
        subprocess.Popen(["cmd", "/c", str(script_path)], creationflags=subprocess.CREATE_NO_WINDOW)


class UpdateWorker(QThread):
    """Runs network work away from the Qt GUI thread."""

    found = Signal(object)
    downloaded = Signal(str)
    progress = Signal(int)
    failed = Signal(str)

    def __init__(self, download_release: ReleaseInfo | None = None, parent=None):
        super().__init__(parent)
        self._download_release = download_release

    def run(self):
        try:
            if self._download_release is None:
                self.found.emit(UpdateService.check())
            else:
                installer = UpdateService.download(self._download_release, self.progress.emit)
                self.downloaded.emit(str(installer))
        except Exception as error:
            self.failed.emit(str(error))