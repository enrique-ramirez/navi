"""The vitals config: the kit's defaults, then the box's own file.

Both files are `KEY=value`, one a line, with `#` comments and blank lines.
They are read by whitelist and never sourced, so a value is literal text and
an unknown key stops the load with the file and line it came from. The box
file is required. Thresholds are integers, and the box overrides any subset
of them.

Run from `vitals/`:
`../_tmp/venv/bin/python -m unittest tests.test_config`
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from config import ConfigError, load

REPO = Path(__file__).resolve().parents[2]
DEFAULTS = REPO / "vitals" / "defaults.conf"
HYRULE_CASTLE = REPO / "hyrule-castle" / "vitals.conf"

# navi's numbers, plus CPU and failed writes (spec criterion 6).
KIT_DEFAULTS = {
    "TEMP_WARN": 65,
    "TEMP_BAD": 75,
    "CPU_WARN": 80,
    "CPU_BAD": 95,
    "MEM_WARN": 85,
    "MEM_BAD": 95,
    "DISK_WARN": 85,
    "DISK_BAD": 95,
    "BACKUP_WARN_H": 36,
    "BACKUP_BAD_H": 72,
    "FAILED_WARN": 1,
}

# Every value differs from every other and from the kit's, so a key read
# into the wrong slot shows.
TEST_DEFAULTS = {key: 11 + n for n, key in enumerate(KIT_DEFAULTS)}

# A complete box file with no thresholds in it.
BOX = """\
HOST=testbox
LABEL=a test box
UNITS=one two
TIMERS=three
BACKUP_GLOB=/tmp/none-*.tar.gz
SERVICES=alpha
RESTARTABLE=alpha
SERVICE_alpha_UNIT=alpha.service
SERVICE_alpha_LOG=journal
SERVICE_alpha_EXTRA=
"""


def line_of(text: str, line: str) -> int:
    return text.splitlines().index(line) + 1


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        # Resolved, so a loader that resolves the path it reports still
        # matches the one the test passed (macOS puts /tmp behind /private).
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.defaults = self.write(
            "defaults.conf", "".join(f"{k}={v}\n" for k, v in TEST_DEFAULTS.items())
        )

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text)
        return path

    def assertBadLine(self, raised: ConfigError, path: Path, line: int, *names: str) -> None:
        message = str(raised)
        prefix = f"{path}:{line}: "
        self.assertTrue(message.startswith(prefix), f"{message!r} does not start with {prefix!r}")
        for name in names:
            self.assertIn(name, message[len(prefix):])

    def test_hyrule_castle_overrides_temperature_and_keeps_every_other_default(self) -> None:
        config = load(DEFAULTS, HYRULE_CASTLE)

        self.assertEqual(config.thresholds, {**KIT_DEFAULTS, "TEMP_WARN": 80, "TEMP_BAD": 90})
        # 80.0 == 80 in Python, so equality alone lets floats or bools through.
        self.assertEqual({type(v) for v in config.thresholds.values()}, {int})
        self.assertEqual(config.host, "hyrule-castle")
        self.assertEqual(config.label, "the services box")
        self.assertEqual(config.units, ["xvfb", "openbox", "foobar2000", "agitha", "host-page"])
        self.assertEqual(config.timers, ["fb2k-backup", "host-status", "host-history"])
        self.assertEqual(config.backup_glob, "/srv/backup/fb2k-state-*.tar.gz")
        # foobar2000 first is the page's order; sorted would put agitha first.
        self.assertEqual(config.services, ["foobar2000", "agitha"])
        self.assertEqual(config.restartable, ["foobar2000", "agitha"])
        self.assertEqual(
            config.service_unit, {"foobar2000": "foobar2000.service", "agitha": "agitha.service"}
        )
        self.assertTrue(config.service_log["foobar2000"].startswith("file:"))
        self.assertEqual(config.service_log["agitha"], "journal")
        self.assertTrue(config.service_extra["foobar2000"].startswith("unplayable:"))
        self.assertEqual(config.service_extra["agitha"], "writes")

    def test_the_kit_defaults_are_navis_numbers_plus_cpu_and_failed_writes(self) -> None:
        config = load(DEFAULTS, self.write("box.conf", BOX))

        self.assertEqual(config.thresholds, KIT_DEFAULTS)

    def test_a_box_overriding_one_threshold_keeps_the_other_ten_at_their_defaults(self) -> None:
        config = load(self.defaults, self.write("box.conf", BOX + "MEM_BAD=99\n"))

        self.assertEqual(config.thresholds, {**TEST_DEFAULTS, "MEM_BAD": 99})

    def test_two_loads_share_no_thresholds(self) -> None:
        first = load(self.defaults, self.write("override.conf", BOX + "TEMP_WARN=99\n"))
        second = load(self.defaults, self.write("plain.conf", BOX))

        self.assertEqual(second.thresholds, TEST_DEFAULTS)
        # A config already handed out keeps its values after the next load.
        self.assertEqual(first.thresholds, {**TEST_DEFAULTS, "TEMP_WARN": 99})

    def test_an_unknown_key_in_the_box_file_names_the_file_line_and_key(self) -> None:
        text = "# a comment\n\n" + BOX + "COLOUR=red\n"
        box = self.write("box.conf", text)

        with self.assertRaises(ConfigError) as caught:
            load(self.defaults, box)

        # The comment and the blank line count, so this is line 13.
        self.assertBadLine(caught.exception, box, line_of(text, "COLOUR=red"), "COLOUR")

    def test_an_unknown_key_in_the_defaults_names_the_defaults_file(self) -> None:
        text = self.defaults.read_text() + "TEMP_CRIT=100\n"
        self.defaults.write_text(text)

        with self.assertRaises(ConfigError) as caught:
            load(self.defaults, self.write("box.conf", BOX))

        self.assertBadLine(caught.exception, self.defaults, line_of(text, "TEMP_CRIT=100"), "TEMP_CRIT")

    def test_a_missing_box_file_names_its_path(self) -> None:
        box = self.tmp / "etc" / "vitals.conf"

        with self.assertRaises(ConfigError) as caught:
            load(self.defaults, box)

        self.assertIn(str(box), str(caught.exception))

    def test_a_service_key_for_a_name_not_in_services_names_the_file_and_line(self) -> None:
        text = BOX + "SERVICE_ghost_UNIT=ghost.service\n"
        box = self.write("box.conf", text)

        with self.assertRaises(ConfigError) as caught:
            load(self.defaults, box)

        self.assertBadLine(caught.exception, box, line_of(text, "SERVICE_ghost_UNIT=ghost.service"))

    def test_a_threshold_that_is_not_an_integer_names_the_file_and_line(self) -> None:
        for value in ("eighty", "8.5", "80%", ""):
            with self.subTest(value=value):
                text = BOX + f"CPU_WARN={value}\n"
                box = self.write("box.conf", text)

                with self.assertRaises(ConfigError) as caught:
                    load(self.defaults, box)

                self.assertBadLine(caught.exception, box, line_of(text, f"CPU_WARN={value}"))

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        text = (
            "# the test box\n"
            "\n"
            "HOST=testbox\n"
            "# HOST=commented-out\n"
            "\n"
            "# MEM_BAD=99\n"
            + BOX.replace("HOST=testbox\n", "")
            + "\n"
        )

        config = load(self.defaults, self.write("box.conf", text))

        self.assertEqual(config.host, "testbox")
        self.assertEqual(config.thresholds, TEST_DEFAULTS)

    def test_a_value_with_command_substitution_is_kept_as_literal_text(self) -> None:
        dollar = self.tmp / "dollar-ran"
        backtick = self.tmp / "backtick-ran"
        label = f"$(touch {dollar})"
        glob = f"`touch {backtick}`"
        text = BOX.replace("LABEL=a test box", f"LABEL={label}").replace(
            "BACKUP_GLOB=/tmp/none-*.tar.gz", f"BACKUP_GLOB={glob}"
        )

        config = load(self.defaults, self.write("box.conf", text))

        self.assertEqual(config.label, label)
        self.assertEqual(config.backup_glob, glob)
        self.assertFalse(dollar.exists())
        self.assertFalse(backtick.exists())


if __name__ == "__main__":
    unittest.main()
