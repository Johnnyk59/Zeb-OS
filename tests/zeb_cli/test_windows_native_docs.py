from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    assert "%LOCALAPPDATA%\\zeb\\zeb-agent\\venv\\Scripts" in doc
    assert "Get-Command zeb        # should print C:\\Users\\<you>\\AppData\\Local\\zeb\\zeb-agent\\venv\\Scripts\\zeb.exe" in doc
    assert '$zebBin = "$InstallDir\\venv\\Scripts"' in install
