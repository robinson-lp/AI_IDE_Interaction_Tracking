"""Tests for the CSV exporter."""

import csv
from datetime import datetime, timezone
from pathlib import Path

from ai_tracker.exporters.csv_exporter import FIELDNAMES, CSVExporter
from ai_tracker.models import Message


def _make_message(
    session_id: str = "sess-1",
    role: str = "human",
    text: str = "Hello",
    tool: str = "claudecode",
    ts: datetime | None = None,
) -> Message:
    return Message(
        session_id=session_id,
        timestamp=ts or datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
        role=role,
        message=text,
        tool=tool,
        file_path="/path/to/session.jsonl",
    )


class TestCSVExporter:
    def test_creates_output_file(self, tmp_path):
        out = tmp_path / "output.csv"
        CSVExporter(out).export([_make_message()])
        assert out.exists()

    def test_creates_parent_directories(self, tmp_path):
        out = tmp_path / "a" / "b" / "output.csv"
        CSVExporter(out).export([_make_message()])
        assert out.exists()

    def test_returns_row_count(self, tmp_path):
        messages = [_make_message() for _ in range(5)]
        count = CSVExporter(tmp_path / "out.csv").export(messages)
        assert count == 5

    def test_header_row_present(self, tmp_path):
        out = tmp_path / "out.csv"
        CSVExporter(out).export([_make_message()])
        with open(out, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == FIELDNAMES

    def test_all_columns_written(self, tmp_path):
        out = tmp_path / "out.csv"
        msg = _make_message(session_id="s1", role="human", text="Q", tool="antigravity")
        CSVExporter(out).export([msg])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        row = rows[0]
        assert row["session_id"] == "s1"
        assert row["role"] == "human"
        assert row["message"] == "Q"
        assert row["tool"] == "antigravity"
        assert "2026-05-20" in row["timestamp"]

    def test_multiple_messages_written(self, tmp_path):
        out = tmp_path / "out.csv"
        messages = [
            _make_message(role="human", text="Question"),
            _make_message(role="assistant", text="Answer"),
        ]
        CSVExporter(out).export(messages)
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert rows[0]["role"] == "human"
        assert rows[1]["role"] == "assistant"

    def test_empty_list_writes_header_only(self, tmp_path):
        out = tmp_path / "out.csv"
        CSVExporter(out).export([])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows == []

    def test_none_timestamp_written_as_empty_string(self, tmp_path):
        out = tmp_path / "out.csv"
        msg = _make_message(ts=None)
        msg.timestamp = None
        CSVExporter(out).export([msg])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["timestamp"] == ""

    def test_unicode_content_preserved(self, tmp_path):
        out = tmp_path / "out.csv"
        CSVExporter(out).export([_make_message(text="こんにちは 🎉")])
        with open(out, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["message"] == "こんにちは 🎉"
