"""Ollama runtime + model installer (cross-platform, user-confirmed).

This module owns everything about *installing* the local runtime and model.
It is deliberately separate from `reviewer.py` (which only *talks* to a
runtime). Nothing here runs without the user's explicit Yes.

Flow (driven by `ensure_model`):
  1. If Ollama is missing, ask to install it, then install on the current
     platform (Windows / macOS / Linux) automatically.
  2. If the model is not pulled, ask to download it, then run `ollama pull`.

Every step is announced; the user can decline (raises `ModelInstallError`) or
Ctrl+C (KeyboardInterrupt propagates; nothing is left half-installed).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Ollama install URLs per platform (official installers).
_OLLAMA_INSTALL_URLS = {
    "darwin": "https://ollama.com/download/Ollama-darwin.zip",
    "linux": "https://ollama.com/install.sh",
    "win32": "https://ollama.com/download/OllamaSetup.exe",
}

DEFAULT_MODEL = "deepseek-r1:7b"

# The only model we install: a reasoning model with the best design/logic
# judgment for review. Kept as a dict so the rank/cleanup machinery stays
# generic if more models are added later.
MODEL_CHOICES: dict[str, tuple[str, str]] = {
    "deepseek-r1:7b": ("~5 GB", "reasoning model — best design/logic judgment"),
}

# Order of preference for auto-selecting the best installed model (largest last).
_MODEL_RANK: dict[str, int] = {
    name: i for i, name in enumerate(MODEL_CHOICES)
}


class ModelInstallError(Exception):
    """Raised when the user declines or interrupts a model install."""


def ensure_model(
    *,
    yes: bool = False,
    confirm: bool = True,
    announce: Any = print,
    model: str | None = None,
    force_menu: bool = False,
) -> None:
    """Ensure the local model is available, asking before any download.

    This is the *only* place a model download can be triggered. It never
    downloads silently:

    - Every step is announced to the user (via `announce`, default stderr).
    - If `confirm` is True (default), the user is asked before any download
      and can decline (raises `ModelInstallError`) or Ctrl+C (KeyboardInterrupt
      propagates; nothing is left half-installed).
    - `yes=True` skips the prompt for scripting/CI, but still prints exactly
      what it is doing.
    - `model` selects which model to pull. If None, the default
      (`deepseek-r1:7b`) is used unless `CODEREVIEW_LLM_MODEL` is set.
    - `force_menu=True` re-selects the model even when one is already
      installed (used by `--setup`).

    The flow is fully automated: if the user answers Yes, the tool installs
    Ollama itself (if missing) and pulls the model — no manual commands.

    Raises:
        ModelInstallError: user declined, or a required step was skipped.
        KeyboardInterrupt: user pressed Ctrl+C during a download.
    """
    if not ollama_installed():
        announce(
            "No local model runtime (Ollama) detected.\n"
            "  This tool can install it for you automatically.\n"
            "  (Or set CODEREVIEW_LLM_URL to any OpenAI-compatible endpoint.)"
        )
        if confirm and not yes:
            answer = input("Install Ollama now? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                raise ModelInstallError("Ollama install declined by user.")
        install_ollama(announce)

    if model is None:
        if force_menu:
            model = _select_model(yes=yes, confirm=confirm, announce=announce)
        else:
            # If a model is already installed, use it without prompting.
            best = pick_best_model()
            if best is not None:
                model = best
            else:
                model = _select_model(yes=yes, confirm=confirm, announce=announce)

    if model_pulled(model):
        announce(f"Model '{model}' already available.")
        _cleanup_smaller_models(model, announce)
        return

    size = MODEL_CHOICES.get(model, ("unknown size", ""))[0]
    announce(
        f"Model '{model}' is not downloaded yet.\n"
        f"  Size: {size}. This will be downloaded to your machine "
        f"and cached by Ollama."
    )
    if confirm and not yes:
        answer = input("Download now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            raise ModelInstallError("Model download declined by user.")

    announce(f"Downloading '{model}' (this may take a while)...")
    binary = _ollama_binary()
    if binary is None:
        raise ModelInstallError("Ollama binary not found.")
    try:
        subprocess.run(
            [binary, "pull", model],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ModelInstallError(f"ollama pull failed (exit {exc.returncode}).") from exc
    except FileNotFoundError as exc:
        raise ModelInstallError("Ollama binary not found.") from exc
    announce(f"Model '{model}' installed.")
    _cleanup_smaller_models(model, announce)


def _select_model(*, yes: bool, confirm: bool, announce: Any) -> str:
    """Pick a model: explicit env var, or the default (deepseek-r1:7b)."""
    return os.environ.get("CODEREVIEW_LLM_MODEL", "") or DEFAULT_MODEL


def pick_best_model() -> str | None:
    """Return the highest-ranked installed model, or None.

    Queries `ollama list` and picks the highest-ranked model from
    `MODEL_CHOICES` that is already pulled. Used by the reviewer so it
    automatically uses the best model the user has, without any config.
    """
    installed = installed_models()
    ranked = [m for m in MODEL_CHOICES if m in installed]
    return ranked[-1] if ranked else None


def installed_models() -> set[str]:
    """Names of all models currently pulled in Ollama."""
    binary = _ollama_binary()
    if binary is None:
        return set()
    try:
        out = subprocess.run(
            [binary, "list"], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()
    names: set[str] = set()
    for line in out.stdout.splitlines()[1:]:  # skip header
        name = line.split()[0].strip() if line.split() else ""
        if name:
            names.add(name)
    return names


def _cleanup_smaller_models(keep: str, announce: Any) -> None:
    """Remove installed models that are no longer the best choice.

    When `keep` is installed, any other model from `MODEL_CHOICES` that ranks
    below it is removed to save disk space. Never touches models outside
    `MODEL_CHOICES`.
    """
    keep_rank = _MODEL_RANK.get(keep)
    if keep_rank is None:
        return  # unknown model; don't delete anything
    binary = _ollama_binary()
    if binary is None:
        return
    for name in installed_models():
        rank = _MODEL_RANK.get(name)
        if rank is not None and rank < keep_rank:
            announce(f"Removing older model '{name}' to free space...")
            try:
                subprocess.run([binary, "rm", name], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                announce(f"  (could not remove '{name}')")


def install_ollama(announce: Any) -> None:
    """Install Ollama on the current platform (Windows/macOS/Linux)."""
    platform = sys.platform
    if platform not in _OLLAMA_INSTALL_URLS:
        raise ModelInstallError(
            f"Unsupported platform '{platform}'. Install Ollama manually from "
            "https://ollama.com, then re-run."
        )
    url = _OLLAMA_INSTALL_URLS[platform]
    announce(f"Installing Ollama for {platform}...")

    if platform == "win32":
        _install_ollama_windows(url, announce)
    elif platform == "darwin":
        _install_ollama_macos(url, announce)
    else:  # linux
        _install_ollama_linux(url, announce)

    if not ollama_installed():
        raise ModelInstallError(
            "Ollama install finished but the 'ollama' command was not found on "
            "PATH. Restart your terminal and re-run, or install manually from "
            "https://ollama.com."
        )


def ollama_installed() -> bool:
    """True if the `ollama` binary is available (PATH or known install dir).

    Checks PATH first, then falls back to the standard install locations per
    platform. This matters right after an install: the current terminal's PATH
    is not refreshed until a new session, but the binary is already on disk.
    """
    return _ollama_binary() is not None


def _ollama_binary() -> str | None:
    """Absolute path to the `ollama` binary, or None if not found."""
    found = shutil.which("ollama")
    if found:
        return found
    return next(
        (str(p) for p in _known_ollama_paths() if p.is_file()),
        None,
    )


def _known_ollama_paths() -> list[Path]:
    """Standard install locations for the `ollama` binary per platform."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        return [
            Path(local) / "Programs" / "Ollama" / "ollama.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
        ]
    if sys.platform == "darwin":
        return [Path("/Applications/Ollama.app/Contents/Resources/ollama")]
    # Linux: /usr/local/bin is the default install target.
    return [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]


def model_pulled(model: str) -> bool:
    """True if `model` is already pulled locally (via `ollama list`)."""
    binary = _ollama_binary()
    if binary is None:
        return False
    try:
        out = subprocess.run(
            [binary, "list"], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    return model in out.stdout


def _install_ollama_windows(url: str, announce: Any) -> None:
    """Download + run the Ollama Windows installer (silent, no admin prompt)."""
    exe = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    announce(f"Downloading installer from {url} ...")
    _download(url, exe, announce)
    announce("Running installer (this may take a minute)...")
    try:
        subprocess.run([str(exe), "/S"], check=True)
    except subprocess.CalledProcessError as exc:
        raise ModelInstallError(f"Ollama installer failed (exit {exc.returncode}).") from exc
    finally:
        try:
            exe.unlink(missing_ok=True)
        except OSError:
            pass


def _install_ollama_macos(url: str, announce: Any) -> None:
    """Download + unzip the Ollama macOS app into /Applications."""
    zip_path = Path(tempfile.gettempdir()) / "Ollama-darwin.zip"
    announce(f"Downloading installer from {url} ...")
    _download(url, zip_path, announce)
    announce("Installing Ollama.app into /Applications...")
    try:
        subprocess.run(
            ["unzip", "-o", str(zip_path), "-d", "/Applications"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ModelInstallError(f"Failed to unzip Ollama (exit {exc.returncode}).") from exc
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass


def _install_ollama_linux(url: str, announce: Any) -> None:
    """Run the official Ollama install script (needs curl + sudo)."""
    announce("Downloading and running the official install script...")
    try:
        subprocess.run(
            ["curl", "-fsSL", url, "|", "sh"],
            shell=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ModelInstallError(f"Ollama install script failed (exit {exc.returncode}).") from exc


def _download(url: str, dest: Path, announce: Any) -> None:
    """Download `url` to `dest` with a simple progress indicator."""
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            _write_chunks(resp, dest, total, announce)
        announce("\r  Download complete.          ")
    except (urllib.error.URLError, OSError) as exc:
        raise ModelInstallError(f"Download failed: {exc}") from exc


def _write_chunks(resp, dest: Path, total: int, announce: Any) -> None:
    """Stream `resp` into `dest`, reporting progress via `announce`."""
    done = 0
    with open(dest, "wb") as fh:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                announce(f"\r  {pct}% ({done // (1024 * 1024)} MB / "
                         f"{total // (1024 * 1024)} MB)", end="")


__all__ = [
    "DEFAULT_MODEL",
    "MODEL_CHOICES",
    "ModelInstallError",
    "ensure_model",
    "install_ollama",
    "installed_models",
    "model_pulled",
    "ollama_installed",
    "pick_best_model",
]
