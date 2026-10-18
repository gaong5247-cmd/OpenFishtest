"""Trusted UCI protocol-parser and sandbox command unit tests.

These tests never execute uploaded programs; live Wine/Fastchess integration
requires the operator's separate disposable rootless Docker VM.
"""
import importlib.util
import sys
from pathlib import Path

from arena_runner import arena_command


def load_uci_probe_parser():
    path = Path(__file__).resolve().parents[1] / "deployment/uci_probe.py"
    spec = importlib.util.spec_from_file_location("trusted_arena_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uci_id_options_auto_parse_and_sanitization():
    probe = load_uci_probe_parser()
    result = probe.parse_uci([
        "id name ExampleFish 0.9.2",
        "id author Chess Lab",
        "option name Hash type spin default 16 min 1 max 1024",
        "option name Threads type spin default 1 min 1 max 32",
        "option name UCI_AnalyseMode type check default false",
    ])
    assert result["name"] == "ExampleFish 0.9.2"
    assert result["version"] == "0.9.2"
    assert result["author"] == "Chess Lab"
    assert result["options"] == [
        {"name":"Hash", "type":"spin", "default":"16"},
        {"name":"Threads", "type":"spin", "default":"1"},
        {"name":"UCI_AnalyseMode", "type":"check", "default":"false"},
    ]
    fallback = probe.parse_uci(["id name RockSolid UCI Engine"], digest="f"*64)
    assert fallback["version"] == "build-" + "f"*12


def test_sandbox_command_runs_only_trusted_launcher(tmp_path):
    challenger = tmp_path / "challenger"
    reference = tmp_path / "reference"
    results = tmp_path / "results"
    challenger.mkdir()
    reference.mkdir()
    results.mkdir()
    book = tmp_path / "book.epd"
    book.write_text("8/8/8/8/8/8/8/8 w - -\n", encoding="utf-8")
    command = arena_command(
        11, challenger, reference, book, results,
        image="openfishtest/arena-wine:0.5"
    )
    assert "--network" in command
    assert command[command.index("--network")+1] == "none"
    assert "cmd=/usr/local/bin/arena-challenger" in command
    assert not any(part == "cmd=/challenger/engine.exe" for part in command)
    assert "--cap-drop" in command
    assert "--read-only" in command
    assert "openfishtest/arena-wine:0.5" in command
    assert "-rounds" in command
    assert command[command.index("-rounds") + 1] == "50"
