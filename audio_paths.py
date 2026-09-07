"""Portable discovery shared by the audio command-line tools."""
from pathlib import Path
import os
import subprocess
import sys
import json
from bundle_integrity import verify_bundle


def configuration():
    path = Path(__file__).resolve().parent / "audio_tools.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("audio_tools.json must contain a JSON object")
    return data


def cobra_path(explicit=None):
    kit = Path(__file__).resolve().parent
    bundled = (kit / "vendor" / "cobra-tools").resolve()
    selected = explicit or os.environ.get("JWE3_COBRA_TOOLS") or configuration().get("cobra_tools")
    if selected:
        path = Path(selected).expanduser().resolve()
        if not (path / "ovl_tool_cmd.py").is_file():
            raise RuntimeError(f"Configured Cobra directory is invalid: {path}")
        if path == bundled:
            verify_bundle(kit / "vendor")
        return path
    candidates = []
    candidates += [kit / "vendor" / "cobra-tools", kit.parent / "cobra-tools-master"]
    for candidate in candidates:
        if Path(candidate).resolve() == bundled and Path(candidate).exists():
            verify_bundle(kit / "vendor")
        if candidate and (Path(candidate) / "ovl_tool_cmd.py").is_file():
            return Path(candidate).resolve()
    raise RuntimeError("Cobra tools not found. Pass --cobra PATH or set JWE3_COBRA_TOOLS "
                       "to the folder containing ovl_tool_cmd.py (with its dependencies installed).")


def run_cobra(args, cobra=None):
    root = cobra_path(cobra)
    result = subprocess.run([sys.executable, str(root / "ovl_tool_cmd.py"), *map(str, args)],
                            cwd=root, capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError("Cobra failed (exit %d):\n%s\n%s" %
                           (result.returncode, result.stdout[-4000:], result.stderr[-4000:]))
    return result.stdout + "\n" + result.stderr


def game_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidates = [os.environ.get("JWE3_GAME"), Path(__file__).resolve().parent, Path.cwd()]
    for candidate in list(candidates):
        if candidate:
            candidates.extend(Path(candidate).resolve().parents)
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
            candidates.append(steam / "steamapps/common/Jurassic World Evolution 3")
            import re
            libraries = steam / "steamapps/libraryfolders.vdf"
            if libraries.exists():
                for root in re.findall(r'"path"\s+"([^"]+)"', libraries.read_text(encoding="utf-8")):
                    candidates.append(Path(root.replace("\\\\", "\\")) / "steamapps/common/Jurassic World Evolution 3")
        except OSError:
            pass
        candidates.append(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) /
                          "Steam/steamapps/common/Jurassic World Evolution 3")
    for candidate in candidates:
        if candidate and (Path(candidate) / "JWE3.exe").is_file():
            return Path(candidate).resolve()
    raise RuntimeError("JWE3 was not found. Pass --game PATH or set JWE3_GAME to the game root.")
