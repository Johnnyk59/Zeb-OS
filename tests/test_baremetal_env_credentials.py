"""Regression coverage for shell-safe bare-metal dashboard credentials."""

import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-baremetal.sh"
CHANGE_PASSWORD_SCRIPT = REPO_ROOT / "scripts" / "change-dashboard-password.sh"
HASH = "scrypt$16384$8$1$c2FsdA==$ZGlnZXN0LWRpZ2VzdA=="
HELPER_START = "# BEGIN bare-metal env helpers"
HELPER_END = "# END bare-metal env helpers"


def _env_helpers(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split(HELPER_START, 1)[1].split(HELPER_END, 1)[0]


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )


def _assert_hash_round_trip(script_path: Path, env_file: Path) -> None:
    result = _run_bash(
        "\n".join(
            [
                "set -euo pipefail",
                f"ZEB_ENV_FILE={shlex.quote(str(env_file))}",
                _env_helpers(script_path),
                f"expected={shlex.quote(HASH)}",
                'set_env_value ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH "$expected"',
                "unset ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH",
                "set -a",
                '# shellcheck disable=SC1090',
                '. "$ZEB_ENV_FILE"',
                "set +a",
                '[[ "$ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH" == "$expected" ]]',
                'printf "%s" "$ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"',
            ]
        )
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == HASH
    assert env_file.read_text(encoding="utf-8") == (
        f"ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH='{HASH}'\n"
    )


def test_installer_migrates_unquoted_scrypt_hash_and_sources_under_nounset(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "zeb.env"
    env_file.write_text(
        "# preserved comment\n"
        f"ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH={HASH}\n"
        "ZEB_TUNNEL_HOSTNAMES=example.test\n",
        encoding="utf-8",
    )

    result = _run_bash(
        "\n".join(
            [
                "set -euo pipefail",
                f"ZEB_ENV_FILE={shlex.quote(str(env_file))}",
                _env_helpers(INSTALL_SCRIPT),
                "password_hash=\"$(read_env_value ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)\"",
                'set_env_value ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH "$password_hash"',
                "password_hash=\"$(read_env_value ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)\"",
                'set_env_value ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH "$password_hash"',
                "unset ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH",
                "set -a",
                '# shellcheck disable=SC1090',
                '. "$ZEB_ENV_FILE"',
                "set +a",
                '[[ "$ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH" == "$password_hash" ]]',
                'printf "%s" "$ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"',
            ]
        )
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == HASH
    assert env_file.read_text(encoding="utf-8") == (
        "# preserved comment\n"
        f"ZEB_DASHBOARD_BASIC_AUTH_PASSWORD_HASH='{HASH}'\n"
        "ZEB_TUNNEL_HOSTNAMES=example.test\n"
    )


def test_installer_hash_write_round_trips_exactly(tmp_path: Path) -> None:
    env_file = tmp_path / "zeb.env"
    env_file.write_text("", encoding="utf-8")
    _assert_hash_round_trip(INSTALL_SCRIPT, env_file)


def test_password_rotation_hash_write_round_trips_exactly(tmp_path: Path) -> None:
    env_file = tmp_path / "zeb.env"
    env_file.write_text("", encoding="utf-8")
    _assert_hash_round_trip(CHANGE_PASSWORD_SCRIPT, env_file)


def test_installer_includes_poppler_for_pdf_drag_and_drop() -> None:
    install_line = next(
        line
        for line in INSTALL_SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.startswith("apt-get install -y python3 ")
    )
    assert "poppler-utils" in install_line.split()
