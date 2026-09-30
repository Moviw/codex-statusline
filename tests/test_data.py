import json
import tempfile
import unittest
from pathlib import Path

from src.data import LogReader, merge_quotas, newest_quotas, parse_title


def token_event(
    timestamp,
    primary_used=0,
    secondary_used=0,
    *,
    primary_window=300,
    secondary_window=10080,
    message="secret text",
):
    return {
        "type": "event_msg",
        "timestamp": timestamp,
        "payload": {
            "type": "token_count",
            "message": message,
            "info": {
                "total_token_usage": {"input_tokens": 123},
                "rate_limits": {
                    "primary": {
                        "used_percent": primary_used,
                        "window_minutes": primary_window,
                        "resets_at": timestamp + 120
                        if isinstance(timestamp, (int, float))
                        else "2026-01-01T00:02:00Z",
                    },
                    "secondary": {
                        "used_percent": secondary_used,
                        "window_minutes": secondary_window,
                        "resets_at": timestamp + 3600
                        if isinstance(timestamp, (int, float))
                        else "2026-01-01T01:00:00Z",
                    },
                },
            },
        },
    }


def line(event):
    return (json.dumps(event) + "\n").encode()


class ParseTitleTests(unittest.TestCase):
    def test_native_context_and_truncated_uuid(self):
        title = "statusline-probe | Context 0% used | 01a0ed06-6030-7992-8ec2-b2cf1..."
        self.assertEqual(
            parse_title(title),
            {
                "model": "statusline-probe",
                "context_used": 0.0,
                "session_hint": "01a0ed06-6030-7992-8ec2-b2cf1...",
            },
        )

    def test_missing_context_is_unknown(self):
        self.assertEqual(
            parse_title("gpt-model | 01a0ed06-6030-7992-8ec2-b2cf1...")["context_used"],
            None,
        )
        self.assertEqual(
            parse_title("gpt-model | Context unknown | 01a0ed06-6030-7992-8ec2-b2cf1...")[
                "context_used"
            ],
            None,
        )
        self.assertIsNone(
            parse_title("gpt-model | Context 101% used | 01a0ed06-6030-7992-8ec2-b2cf1...")[
                "context_used"
            ]
        )
        self.assertIsNone(
            parse_title(
                "gpt-model | Context " + "9" * 400 + "% used | 01a0ed06-6030-7992-8ec2-b2cf1..."
            )["context_used"]
        )

    def test_rejects_malformed_title_instead_of_guessing(self):
        for title in (
            " | Context 0% used | 01a0ed06-6030-7992-8ec2-b2cf1...",
            "model | context 0% | 01a0ed06-6030-7992-8ec2-b2cf1...",
            "model | Context 0% used | not-a-thread",
            "model | Context 0% used | 01a0ed06-6030-7992-8ec2-b2cf1... | extra",
        ):
            with self.subTest(title=title), self.assertRaises(ValueError):
                parse_title(title)


class LogReaderTests(unittest.TestCase):
    def test_reads_only_matching_quota_windows_and_keeps_no_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_bytes(line(token_event(1000, 23.5, 60)))
            reader = LogReader()
            result = reader.update(str(path))
            self.assertEqual(result["quotas"]["5h"]["remaining"], 76.5)
            self.assertEqual(result["quotas"]["weekly"]["remaining"], 40.0)
            self.assertEqual(result["quotas"]["5h"]["reset_at"], 1120.0)
            self.assertEqual(result["quotas"]["5h"]["observed_at"], 1000.0)
            self.assertNotIn("secret", repr(result))
            self.assertNotIn("secret", repr(reader.__dict__))

    def test_session_tokens_follow_latest_event_and_reset_on_path_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a.jsonl", Path(tmp) / "b.jsonl"
            event = token_event(1000)
            event["payload"]["info"]["total_token_usage"] = {"total_tokens": 1_500_000}
            first.write_bytes(line(token_event(900)) + line(event))
            second.write_bytes(
                line({"type": "event_msg", "timestamp": 1, "payload": {"type": "other"}})
            )
            reader = LogReader()
            self.assertEqual(reader.update(str(first))["tokens"], 1_500_000.0)
            self.assertIsNone(reader.update(str(second))["tokens"])

    def test_weekly_only_plan_in_primary_slot(self):
        # Plus plans may report only the weekly window, placed in "primary".
        event = token_event(1000, primary_used=11, primary_window=10080)
        event["payload"]["info"]["rate_limits"]["secondary"] = None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_bytes(line(event))
            quotas = LogReader().update(str(path))["quotas"]
        self.assertEqual(quotas["weekly"]["remaining"], 89.0)
        self.assertIsNone(quotas["5h"]["remaining"])

    def test_newest_quota_across_sessions_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "2026" / "09" / "30"
            day.mkdir(parents=True)
            (day / "old.jsonl").write_bytes(line(token_event(1000, 80, 10)))
            (day / "new.jsonl").write_bytes(line(token_event(2000, 5, 20)))
            others = newest_quotas(Path(tmp), {})
        self.assertEqual(others["5h"]["remaining"], 95.0)
        self.assertEqual(others["weekly"]["observed_at"], 2000.0)
        bound = {"5h": {"remaining": 50.0, "observed_at": 3000.0}, "weekly": {"observed_at": None}}
        merged = merge_quotas(bound, others)
        self.assertEqual(merged["5h"]["remaining"], 50.0)
        self.assertEqual(merged["weekly"]["remaining"], 80.0)
        self.assertEqual(newest_quotas(Path(tmp) / "missing", {}), {})

    def test_quota_only_payload_can_have_null_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            event = token_event(1000, 25, 50)
            rate_limits = event["payload"]["info"].pop("rate_limits")
            event["payload"]["info"] = None
            event["payload"]["rate_limits"] = rate_limits
            path.write_bytes(line(event))
            result = LogReader().update(str(path))["quotas"]
            self.assertEqual(result["5h"]["remaining"], 75.0)
            self.assertEqual(result["weekly"]["remaining"], 50.0)

    def test_incremental_partial_line_and_non_refill_reset_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            first = line(token_event(1000, 80, 90))
            path.write_bytes(first)
            reader = LogReader()
            self.assertEqual(reader.update(str(path))["quotas"]["5h"]["remaining"], 20.0)

            partial = json.dumps(token_event(1100, 30, 50)).encode()
            with path.open("ab") as f:
                f.write(partial[:30])
            self.assertEqual(reader.update(str(path))["quotas"]["5h"]["remaining"], 20.0)
            with path.open("ab") as f:
                f.write(partial[30:] + b"\n")
            result = reader.update(str(path))
            self.assertEqual(result["quotas"]["5h"]["remaining"], 70.0)
            self.assertEqual(result["quotas"]["weekly"]["remaining"], 50.0)

    def test_malformed_lines_unknown_windows_and_old_events_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            good = token_event(2000, 25, 40)
            old = token_event(1500, 1, 2)
            wrong_window = token_event(3000, 0, 0, primary_window=60, secondary_window=60)
            path.write_bytes(b"{bad json}\n" + line(good) + line(old) + line(wrong_window))
            result = LogReader().update(str(path))["quotas"]
            self.assertEqual(result["5h"]["remaining"], 75.0)
            self.assertEqual(result["weekly"]["remaining"], 60.0)
            self.assertEqual(result["5h"]["observed_at"], 2000.0)

    def test_same_directory_sessions_are_explicitly_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "a.jsonl"
            path_b = Path(tmp) / "b.jsonl"
            path_a.write_bytes(line(token_event(1000, 10, 20)))
            path_b.write_bytes(line(token_event(1000, 70, 80)))
            reader_a, reader_b = LogReader(), LogReader()
            self.assertEqual(reader_a.update(str(path_a))["quotas"]["5h"]["remaining"], 90.0)
            self.assertEqual(reader_b.update(str(path_b))["quotas"]["5h"]["remaining"], 30.0)
            self.assertEqual(reader_a.update(str(path_a))["quotas"]["weekly"]["remaining"], 80.0)

    def test_path_switch_and_truncation_reset_previous_session_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.jsonl"
            b = Path(tmp) / "b.jsonl"
            a.write_bytes(line(token_event(1000, 15, 25)))
            b.write_bytes(line(token_event(1000, 55, 65)))
            reader = LogReader()
            self.assertEqual(reader.update(str(a))["quotas"]["5h"]["remaining"], 85.0)
            self.assertEqual(reader.update(str(b))["quotas"]["5h"]["remaining"], 45.0)

            # Truncating and replacing the same path begins a fresh generation.
            a.write_bytes(line(token_event(2000, 90, 95)))
            self.assertEqual(reader.update(str(b))["quotas"]["5h"]["remaining"], 45.0)
            self.assertEqual(reader.update(str(a))["quotas"]["5h"]["remaining"], 10.0)

    def test_same_path_truncation_starts_a_fresh_file_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_bytes(line(token_event(1000, 20, 30)))
            reader = LogReader()
            self.assertEqual(reader.update(str(path))["quotas"]["5h"]["remaining"], 80.0)
            path.write_bytes(line(token_event(2000, 90, 95)))
            result = reader.update(str(path))["quotas"]
            self.assertEqual(result["5h"]["remaining"], 10.0)
            self.assertEqual(result["5h"]["observed_at"], 2000.0)

    def test_initial_read_of_oversized_log_is_bounded_and_uses_tail_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            filler = b'{"type":"noise","payload":"' + b"x" * (1024 * 1024 + 100) + b'"}\n'
            path.write_bytes(filler + line(token_event(2000, 40, 50)))
            reader = LogReader()
            result = reader.update(str(path))["quotas"]
            self.assertEqual(result["5h"]["remaining"], 60.0)
            self.assertEqual(result["weekly"]["remaining"], 50.0)
            self.assertLessEqual(reader._offset, len(filler) + len(line(token_event(2000, 40, 50))))

    def test_unterminated_oversized_record_is_discarded_with_bounded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_bytes(b"x" * (1024 * 1024 + 7))
            reader = LogReader()
            reader.update(str(path))
            self.assertLessEqual(len(reader._partial), 1024 * 1024)
            self.assertTrue(reader._discard_until_newline)
            self.assertEqual(reader._partial, b"")
            with path.open("ab") as f:
                f.write(b"still oversized\n" + line(token_event(2000, 30, 40)))
            result = reader.update(str(path))["quotas"]
            self.assertEqual(result["5h"]["remaining"], 70.0)

    def test_empty_update_preserves_probe_for_same_size_overwrite_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_bytes(line(token_event(1000, 20, 30)))
            reader = LogReader()
            reader.update(str(path))
            probe = reader._probe
            reader.update(str(path))  # no appended bytes
            self.assertEqual(reader._probe, probe)
            path.write_bytes(line(token_event(2000, 90, 95)))
            self.assertEqual(reader.update(str(path))["quotas"]["5h"]["remaining"], 10.0)

    def test_unobserved_quotas_are_unknown_not_fabricated_full_allowance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_bytes(b"")
            result = LogReader().update(str(path))["quotas"]
            self.assertIsNone(result["5h"]["remaining"])
            self.assertIsNone(result["weekly"]["observed_at"])


if __name__ == "__main__":
    unittest.main()
