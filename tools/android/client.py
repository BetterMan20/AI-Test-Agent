"""ADB client for Android device automation."""

from __future__ import annotations

import shutil
import subprocess

from execution.exceptions import ToolError


class ADBClient:
    """通过 subprocess 调用 adb 命令操作 Android 设备。"""

    def __init__(self, device_serial: str = "", timeout: int = 30):
        self._serial = device_serial
        self._timeout = timeout

    def _adb(self, *args: str) -> str:
        if shutil.which("adb") is None:
            raise ToolError("adb", "adb not found in PATH")
        cmd = ["adb"]
        if self._serial:
            cmd.extend(["-s", self._serial])
        cmd.extend(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if result.returncode != 0:
                raise ToolError("adb", result.stderr.strip() or "Unknown error")
            return result.stdout
        except subprocess.TimeoutExpired:
            raise ToolError("adb", f"Command timed out: {' '.join(args)}")

    def shell(self, command: str) -> str:
        return self._adb("shell", command)

    def screenshot(self, save_path: str) -> str:
        remote = "/sdcard/_test_screenshot.png"
        self._adb("shell", "screencap", "-p", remote)
        self._adb("pull", remote, save_path)
        self._adb("shell", "rm", remote)
        return save_path

    def pull(self, remote: str, local: str) -> str:
        return self._adb("pull", remote, local)

    def push(self, local: str, remote: str) -> str:
        return self._adb("push", local, remote)

    def logcat(self, filter_spec: str = "", dump: bool = True) -> str:
        args = ["logcat"]
        if dump:
            args.append("-d")
        if filter_spec:
            args.append(filter_spec)
        return self._adb(*args)

    def install(self, apk_path: str, replace: bool = True) -> str:
        args = ["install"]
        if replace:
            args.append("-r")
        args.append(apk_path)
        return self._adb(*args)

    def uninstall(self, package: str) -> str:
        return self._adb("uninstall", package)

    def get_device_info(self) -> dict[str, str]:
        model = self._adb("shell", "getprop", "ro.product.model").strip()
        version = self._adb("shell", "getprop", "ro.build.version.release").strip()
        sdk = self._adb("shell", "getprop", "ro.build.version.sdk").strip()
        return {"model": model, "version": version, "sdk": sdk}
