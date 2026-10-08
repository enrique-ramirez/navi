"""The vitals config: the kit's defaults, then the box's own file.

Reads two files of `KEY=value` lines (`#` comments and blank lines allowed):
`defaults.conf`, which sits beside this module in the installed kit
(`/usr/local/lib/vitals/` on hyrule-castle), and the box file
(`/etc/vitals.conf`, a copy of `hyrule-castle/vitals.conf`). The box file
overrides the defaults and is required.

Nothing is sourced or expanded: a value is literal text, and a key outside
the whitelist stops the load with the file and line it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

THRESHOLD_KEYS = (
    "TEMP_WARN",
    "TEMP_BAD",
    "CPU_WARN",
    "CPU_BAD",
    "MEM_WARN",
    "MEM_BAD",
    "DISK_WARN",
    "DISK_BAD",
    "BACKUP_WARN_H",
    "BACKUP_BAD_H",
    "FAILED_WARN",
)
_BOX_KEYS = ("HOST", "LABEL", "UNITS", "TIMERS", "BACKUP_GLOB", "SERVICES", "RESTARTABLE")
_SERVICE_KEY = re.compile(r"SERVICE_([a-z0-9]+)_(UNIT|LOG|EXTRA)")
_NAME = re.compile(r"[a-z0-9]+")


class ConfigError(Exception):
    """A bad line starts `<file>:<line>: `; a missing or incomplete file names its path."""


@dataclass
class Config:
    host: str
    label: str
    units: list[str]
    timers: list[str]
    backup_glob: str
    services: list[str]
    restartable: list[str]
    service_unit: dict[str, str]
    service_log: dict[str, str]
    service_extra: dict[str, str]
    thresholds: dict[str, int]


@dataclass
class _Entry:
    path: Path
    line: int
    value: str


def _bad(path: Path, line: int, message: str) -> ConfigError:
    return ConfigError(f"{path}:{line}: {message}")


def _is_log(value: str) -> bool:
    return value in ("journal", "off") or _has_argument(value, "file:")


def _is_extra(value: str) -> bool:
    return value in ("", "writes") or _has_argument(value, "unplayable:")


def _has_argument(value: str, prefix: str) -> bool:
    return value.startswith(prefix) and value != prefix


def _read(path: Path, allow_box_keys: bool) -> dict[str, _Entry]:
    try:
        text = path.read_text()
    except OSError as error:
        raise ConfigError(f"{path}: cannot read config file ({error.strerror or error})") from error

    entries: dict[str, _Entry] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if not separator:
            raise _bad(path, number, f"expected KEY=value, got {stripped!r}")
        if key in THRESHOLD_KEYS:
            if not re.fullmatch(r"0|[1-9][0-9]*", value):
                raise _bad(path, number, f"{key} must be a whole number of 0 or more, no leading zero, got {value!r}")
        elif allow_box_keys and (key in _BOX_KEYS or _SERVICE_KEY.fullmatch(key)):
            pass
        else:
            raise _bad(path, number, f"unknown key {key!r}")
        entries[key] = _Entry(path, number, value)
    return entries


def load(defaults: Path, box: Path) -> Config:
    defaults, box = Path(defaults), Path(box)
    kit = _read(defaults, allow_box_keys=False)
    own = _read(box, allow_box_keys=True)

    merged = {**kit, **own}
    thresholds: dict[str, int] = {}
    for key in THRESHOLD_KEYS:
        if key not in merged:
            raise ConfigError(f"{defaults}: no {key}")
        thresholds[key] = int(merged[key].value)

    for key in ("HOST", "SERVICES"):
        if key not in own:
            raise ConfigError(f"{box}: no {key}")
    services = own["SERVICES"].value.split()
    for name in services:
        if not _NAME.fullmatch(name):
            raise _bad(box, own["SERVICES"].line, f"service name {name!r} must match [a-z0-9]+")
        # The sampler's own files and state are named `box` (log-box.json, box.cursor), so a service by that name would share them.
        if name == "box":
            raise _bad(box, own["SERVICES"].line, "a service cannot be named 'box'; the box's own log and state use that name")
    restartable = own["RESTARTABLE"].value.split() if "RESTARTABLE" in own else []
    for name in restartable:
        if name not in services:
            raise _bad(box, own["RESTARTABLE"].line, f"{name!r} is restartable but not in SERVICES")

    service_unit: dict[str, str] = {}
    service_log: dict[str, str] = {}
    service_extra: dict[str, str] = {}
    found = {"UNIT": service_unit, "LOG": service_log, "EXTRA": service_extra}
    for key, entry in own.items():
        match = _SERVICE_KEY.fullmatch(key)
        if not match:
            continue
        name, field = match.groups()
        if name not in services:
            raise _bad(box, entry.line, f"{key} is for {name!r}, which is not in SERVICES")
        if field == "LOG" and not _is_log(entry.value):
            raise _bad(box, entry.line, f"{key} must be journal, file:<folder> or off, got {entry.value!r}")
        if field == "EXTRA" and not _is_extra(entry.value):
            raise _bad(box, entry.line, f"{key} must be writes, unplayable:<path> or empty, got {entry.value!r}")
        found[field][name] = entry.value

    for name in services:
        if name not in service_unit:
            raise ConfigError(f"{box}: no SERVICE_{name}_UNIT")

    def value(key: str) -> str:
        return own[key].value if key in own else ""

    return Config(
        host=value("HOST"),
        label=value("LABEL"),
        units=value("UNITS").split(),
        timers=value("TIMERS").split(),
        backup_glob=value("BACKUP_GLOB"),
        services=services,
        restartable=restartable,
        service_unit={name: service_unit[name] for name in services},
        service_log={name: service_log.get(name, "off") for name in services},
        service_extra={name: service_extra.get(name, "") for name in services},
        thresholds=thresholds,
    )
