import configparser
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deepwick_spec.ansi import line_with, runs, style_of
from deepwick_spec.check_port import check_port
from deepwick_spec.palette import load_palette
from deepwick_spec.tui import capture, tmux_available

REPO = Path(__file__).resolve().parents[1]
PALETTE = load_palette()
C = PALETTE.colors
sys.path.insert(0, str(REPO))
IMAGE = "docker.io/library/postgres:17"
RC = REPO / "deepwick.pgclirc"
TOKENS = {
    "Comment": ("comment", "italic"), "Keyword": ("blue", ""), "Name.Builtin": ("teal", ""),
    "String": ("orange", ""), "String.Name": ("lightBlue", ""), "Number": ("sage", ""),
    "Operator": ("foreground", ""), "Punctuation": ("foreground", ""),
    "Token.Output.TableSeparator": ("muted", ""), "Token.Output.Header": ("blue", "bold"),
    "Token.Output.Null": ("muted", ""),
}
COLORS = {
    "prompt": "bold #569CD6",
    "completion-menu.completion": "bg:#10192C #D4D4D4",
    "completion-menu.completion.current": "bg:#264F78 #D4D4D4",
    "completion-menu.meta.completion": "bg:#10192C #7A86A8",
    "bottom-toolbar": "bg:#10192C #D4D4D4",
    "bottom-toolbar.transaction.valid": "bg:#10192C #57A64A bold",
    "bottom-toolbar.transaction.failed": "bg:#10192C #F44747 bold",
    "search": "#D4D4D4 bg:#264F78",
    "search.current": "#D7BA7D bg:#264F78",
    "output.header": "bold #569CD6",
    "output.null": "#6E7899",
}



def isolated_env(tmp_path, **extra):
    dirs = {"HOME": tmp_path / "home"}
    for kind in ("CONFIG", "DATA", "STATE", "CACHE"):
        dirs[f"XDG_{kind}_HOME"] = tmp_path / kind.lower()
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = {key: str(path) for key, path in dirs.items()}
    env.update({key: str(value) for key, value in extra.items()})
    return env


def style_containing(text, needle):
    for chunk, style in runs(text):
        if needle in chunk:
            return style
    raise AssertionError(f"no run contains {needle!r}")


def has_bg(text, name):
    return any(style["bg"] == C[name].lower() for _, style in runs(text))


def has_fg(text, name):
    return any(style["fg"] == C[name].lower() for _, style in runs(text))


def token(path):
    from pygments import token as t

    node = t.Token
    for part in path.removeprefix("Token.").split("."):
        node = getattr(node, part)
    return node


def test_style_tokens():
    from deepwick_pygments import DeepwickStyle

    for path, (name, attr) in TOKENS.items():
        style = DeepwickStyle.style_for_token(token(path))
        assert (style["color"] or "").lower() == C[name].lstrip("#").lower(), path
        assert style["italic"] == (attr == "italic") and style["bold"] == (attr == "bold"), path
    assert DeepwickStyle.background_color == C["background"]


def pgclirc():
    assert RC.is_file(), "deepwick.pgclirc missing"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(RC.read_text(encoding="utf-8"))
    return parser


def test_pgclirc_selects_style_and_colors():
    p = pgclirc()
    assert p["main"]["syntax_style"] == "deepwick"
    colors = {k: v.strip("'") for k, v in p["colors"].items()}
    for key, value in COLORS.items():
        assert colors[key] == value, key


@pytest.fixture(scope="session")
def venv(tmp_path_factory):
    if shutil.which("uv") is None:
        pytest.skip("requires uv")
    path = tmp_path_factory.mktemp("venv")
    subprocess.run(["uv", "venv", "-q", str(path)], check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(path / "bin" / "python"), "pgcli==4.6.0", str(REPO)], check=True)
    return path


def test_entry_point_registers_style(venv):
    out = subprocess.run([str(venv / "bin" / "python"), "-c",
                          "from pygments.styles import get_style_by_name; print(get_style_by_name('deepwick').__name__)"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "DeepwickStyle"


@pytest.fixture(scope="session")
def postgres():
    if shutil.which("podman") is None or subprocess.run(["podman", "image", "exists", IMAGE]).returncode != 0:
        pytest.skip(f"requires podman and the local image {IMAGE}")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cid = subprocess.run(["podman", "run", "-d", "--rm", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                          "-p", f"127.0.0.1:{port}:5432", IMAGE], check=True, capture_output=True, text=True).stdout.strip()
    try:
        seed = "CREATE TABLE fixture (id int, label text); INSERT INTO fixture VALUES (1, 'deepwick'), (2, NULL);"
        for _ in range(60):
            if subprocess.run(["podman", "exec", cid, "psql", "-U", "postgres", "-h", "127.0.0.1", "-c", seed],
                              capture_output=True).returncode == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail("postgres did not become ready")
        yield port
    finally:
        subprocess.run(["podman", "stop", "-t", "1", cid], capture_output=True)


MERGE = r'''
import sys
from pathlib import Path
import pgcli
from configobj import ConfigObj
from pgcli.config import write_default_config
rc, theme = sys.argv[1], sys.argv[2]
write_default_config(str(Path(pgcli.__file__).with_name("pgclirc")), rc)
cfg = ConfigObj(rc, encoding="utf-8", list_values=False, interpolation=False)
cfg["main"]["syntax_style"] = "deepwick"
cfg["colors"] = ConfigObj(theme, encoding="utf-8", list_values=False, interpolation=False)["colors"]
cfg.write()
'''


def merged_config(venv, dest):
    """The README's install: the default pgclirc with syntax_style set and [colors] replaced."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(venv / "bin" / "python"), "-c", MERGE, str(dest), str(RC)], check=True)
    return dest


def pgcli_env(tmp_path, venv):
    env = isolated_env(tmp_path, TERM="xterm-256color", PROMPT_TOOLKIT_COLOR_DEPTH="DEPTH_24_BIT", PAGER="cat")
    merged_config(venv, Path(env["XDG_CONFIG_HOME"]) / "pgcli" / "config")
    return env


def test_readme_merge_loads(tmp_path, venv):
    rc = merged_config(venv, tmp_path / "config")
    code = "import sys; from pgcli.main import PGCli; p = PGCli(pgclirc_file=sys.argv[1]); print(p.syntax_style)"
    out = subprocess.run([str(venv / "bin" / "python"), "-c", code, str(rc)], capture_output=True, text=True,
                         env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[-1] == "deepwick"


def pgcli_command(venv, port):
    return f"{venv / 'bin' / 'pgcli'} --less-chatty -h 127.0.0.1 -p {port} -U postgres -d postgres"


requires_tmux = pytest.mark.skipif(not tmux_available(), reason="requires tmux")


@requires_tmux
def test_pgcli_prompt_and_syntax(tmp_path, venv, postgres):
    out = capture(pgcli_command(venv, postgres), pgcli_env(tmp_path, venv), size=(110, 24), wait_for="postgres>",
                  literal="SELECT 'hi', 42 -- note", after="note", timeout=30)
    prompt = style_containing(out, "postgres@")
    assert (prompt["fg"], prompt["bold"]) == (C["blue"].lower(), True)
    assert style_of(out, "SELECT")["fg"] == C["blue"].lower(), "syntax_style fell back to native"
    assert style_of(out, "'hi'")["fg"] == C["orange"].lower()
    assert style_of(out, "42")["fg"] == C["sage"].lower()
    comment = style_of(out, "-- note")
    assert (comment["fg"], comment["italic"]) == (C["comment"].lower(), True)
    assert has_bg(out, "surface"), "bottom toolbar should be on Surface"


@requires_tmux
def test_pgcli_table_output(tmp_path, venv, postgres):
    out = capture(pgcli_command(venv, postgres), pgcli_env(tmp_path, venv), size=(110, 24), wait_for="postgres>",
                  literal="SELECT id, label FROM fixture ORDER BY id;", keys=("Enter",), after="SELECT 2", timeout=30)
    header = runs(line_with(out, "| label"))
    assert any("label" in chunk and s["fg"] == C["blue"].lower() and s["bold"] for chunk, s in header)
    assert style_containing(out, "+-")["fg"] == C["muted"].lower()
    assert style_containing(out, "<null>")["fg"] == C["muted"].lower()


def test_port_conventions():
    assert check_port(REPO, PALETTE.allowed_hex()) == []
