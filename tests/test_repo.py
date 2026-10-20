"""Guards for the repository: documentation, licenses, secrets, changelog."""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
README_EN = ROOT / "README.md"
README_DE = ROOT / "README.de.md"


def _strip_code(text):
    return re.sub(r"```.*?```|`[^`\n]*`", "", text, flags=re.S)


def _anchor(heading):
    """GitHub's heading anchor: lower case, punctuation removed, spaces to '-'."""
    a = heading.strip().lower()
    a = re.sub(r"[^\w\- ]", "", a, flags=re.UNICODE)
    return a.replace(" ", "-")


def _markdown_files():
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode("utf-8")
    return [ROOT / f for f in out.split("\0") if f]


def test_both_readmes_have_the_same_sections():
    en = re.findall(r"^## ", README_EN.read_text(encoding="utf-8"), re.M)
    de = re.findall(r"^## ", README_DE.read_text(encoding="utf-8"), re.M)
    assert len(en) == len(de) >= 8


def _media(path):
    text = path.read_text(encoding="utf-8")
    return re.findall(r'src="(docs/media/[^"]+)"', text)


def test_both_readmes_show_the_same_media_in_their_language():
    en, de = _media(README_EN), _media(README_DE)
    assert [m.replace(".en.", ".") for m in en] == [m.replace(".de.", ".") for m in de]
    assert not any(".de." in m for m in en)
    assert not any(".en." in m for m in de)


def test_every_media_file_is_used_and_exists():
    used = set(_media(README_EN)) | set(_media(README_DE))
    for m in used:
        assert (ROOT / m).exists(), m
    files = {f"docs/media/{p.name}" for p in (ROOT / "docs" / "media").iterdir()
             if p.suffix in (".gif", ".png", ".jpg", ".webp")}
    assert files == used, f"unused: {files - used}"


def test_every_image_has_alt_text():
    for path in (README_EN, README_DE):
        for tag in re.findall(r"<img [^>]+>", path.read_text(encoding="utf-8")):
            assert 'alt="' in tag, tag


def test_no_dead_local_links_or_anchors():
    for md in _markdown_files():
        text = _strip_code(md.read_text(encoding="utf-8"))
        anchors = {_anchor(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
        for a, b in re.findall(r"\]\(<?([^)\s>]+)>?[^)]*\)|(?:src|href)=\"([^\"]+)\"", text):
            target = a or b
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            path, _, frag = target.partition("#")
            if not path:
                assert frag in anchors, f"{md.name}: #{frag}"
                continue
            base = ROOT if path.startswith("/") else md.parent
            assert (base / path.lstrip("/")).exists(), f"{md.name}: {target}"


def test_troubleshooting_anchor_used_by_the_issue_config_exists():
    assert "## Troubleshooting" in README_EN.read_text(encoding="utf-8")
    assert "#troubleshooting" in (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(
        encoding="utf-8")


def test_no_control_characters_in_documents():
    for md in _markdown_files():
        text = md.read_text(encoding="utf-8")
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text), md.name


def test_changelog_has_an_entry_for_the_current_version():
    from fluneit import app
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(app.__version__)}\] - \d{{4}}-\d\d-\d\d$",
                     changelog, re.M)


def test_license_and_notices_are_bundled_into_the_exe():
    build = (ROOT / "packaging" / "build_exe.ps1").read_text(encoding="utf-8")
    assert "LICENSE" in build and "THIRD-PARTY-NOTICES.md" in build
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_secrets_guard_passes():
    subprocess.run([sys.executable, "scripts/check_secrets.py"], cwd=ROOT, check=True)
