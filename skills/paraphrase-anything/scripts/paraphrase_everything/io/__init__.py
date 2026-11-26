"""Format-preserving I/O (stories 006, 029).

Each format module exposes ``extract(source, **options) -> segments``,
``rebuild(source, rewritten, **options)``, and ``SPECS``: one dict per format it reads, with

- ``name``: the format id (``vtt`` shares the ``srt`` module, so that module has two specs);
- ``extensions``: file extensions that select it; ``output``: the extension of a rebuilt file;
- ``sniff``: optional ``callable(source) -> bool`` for detection without an extension, tried in
  ``priority`` order (highest first); ``fallback: True`` marks the format used when none matches;
- ``options``: optional ``{name: {"type": "str"|"list"|"bool"|"int", "help": ...}}`` passed to
  ``extract`` / ``rebuild`` as keyword arguments (``--format-option name=value`` on the CLI).

Modules in this package are discovered at import, so adding a format is adding a module.
"""

import importlib
import pkgutil
from pathlib import Path

from .base import FormatError, public

OPTION_TYPES = ("str", "list", "bool", "int")
_SPEC_KEYS = {"name", "extensions", "output", "sniff", "priority", "fallback", "options"}
_PRIVATE = {"base"}


def _check_spec(spec, module):
    """Raise ``FormatError`` when a format spec is malformed."""
    where = f"format module {module.__name__}"
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str) or not spec["name"]:
        raise FormatError(f"{where}: every spec needs a string name")
    unknown = sorted(set(spec) - _SPEC_KEYS)
    if unknown:
        raise FormatError(f"{where}: unknown spec keys {', '.join(unknown)}")
    exts = spec.get("extensions", [])
    if not isinstance(exts, (list, tuple)) or not all(isinstance(e, str) and e.startswith(".") for e in exts):
        raise FormatError(f"{where}: extensions must be a list like ['.md']")
    if not isinstance(spec.get("output"), str) or not spec["output"].startswith("."):
        raise FormatError(f"{where}: output must be an extension like '.md'")
    if spec.get("sniff") is not None and not callable(spec["sniff"]):
        raise FormatError(f"{where}: sniff must be callable")
    for name, option in spec.get("options", {}).items():
        if not isinstance(option, dict) or option.get("type") not in OPTION_TYPES:
            raise FormatError(f"{where}: option {name} needs a type in {', '.join(OPTION_TYPES)}")
    for attr in ("extract", "rebuild"):
        if not callable(getattr(module, attr, None)):
            raise FormatError(f"{where}: missing {attr}()")


class Registry:
    """Every known format: its module, spec, extensions, and detection order."""

    def __init__(self, modules):
        """Collect the ``SPECS`` of ``modules``; names and extensions must be unique."""
        self.modules, self.specs, self.extensions = {}, {}, {}
        self.fallback = None
        for module in modules:
            for spec in getattr(module, "SPECS", ()):
                _check_spec(spec, module)
                name = spec["name"]
                if name in self.specs:
                    raise FormatError(f"format {name} is registered twice")
                self.modules[name], self.specs[name] = module, dict(spec)
                for ext in spec.get("extensions", []):
                    if ext.lower() in self.extensions:
                        raise FormatError(f"extension {ext} is claimed by {self.extensions[ext.lower()]} and {name}")
                    self.extensions[ext.lower()] = name
                if spec.get("fallback"):
                    if self.fallback:
                        raise FormatError(f"two fallback formats: {self.fallback} and {name}")
                    self.fallback = name
        if self.fallback is None:
            raise FormatError("no fallback format is registered")
        sniffers = [s for s in self.specs.values() if s.get("sniff")]
        self.sniff_order = [s["name"] for s in sorted(sniffers, key=lambda s: -s.get("priority", 0))]

    def names(self):
        """Format names, sorted."""
        return sorted(self.specs)

    def outputs(self):
        """``{name: output extension}`` of every format."""
        return {name: spec["output"] for name, spec in self.specs.items()}

    def detect(self, source, path=None):
        """Pick a format from the file extension, else by sniffing the content, else the fallback."""
        if path:
            fmt = self.extensions.get(Path(path).suffix.lower())
            if fmt:
                return fmt
        for name in self.sniff_order:
            if self.specs[name]["sniff"](source):
                return name
        return self.fallback

    def module(self, fmt):
        """The module for ``fmt``, or ``FormatError``."""
        try:
            return self.modules[fmt]
        except KeyError:
            raise FormatError(f"unknown format: {fmt} (choose from {', '.join(self.names())})") from None

    def options(self, fmt, pairs):
        """Parse ``["key=value", ...]`` or a dict against the options ``fmt`` declares."""
        self.module(fmt)
        declared = self.specs[fmt].get("options", {})
        items = pairs.items() if isinstance(pairs, dict) else [_split_pair(p) for p in pairs or ()]
        parsed = {}
        for key, value in items:
            if key not in declared:
                known = ", ".join(sorted(declared)) or "-"
                raise FormatError(f"format {fmt} has no option {key!r} (declared: {known})")
            parsed[key] = _convert(key, value, declared[key]["type"])
        return parsed


def _split_pair(pair):
    """``"key=value"`` as ``(key, value)``."""
    key, sep, value = pair.partition("=")
    if not sep or not key.strip():
        raise FormatError(f"format option must be key=value, got {pair!r}")
    return key.strip(), value.strip()


def _convert(key, value, kind):
    """Convert an option value given as text (or already typed) to ``kind``."""
    if not isinstance(value, str):
        ok = {"list": isinstance(value, list), "bool": isinstance(value, bool),
              "int": isinstance(value, int) and not isinstance(value, bool), "str": False}[kind]
        if not ok:
            raise FormatError(f"option {key} must be a {kind}")
        return value
    if kind == "list":
        return [v.strip() for v in value.split(",") if v.strip()]
    if kind == "bool":
        if value.lower() not in ("true", "false", "1", "0"):
            raise FormatError(f"option {key} must be true or false")
        return value.lower() in ("true", "1")
    if kind == "int":
        try:
            return int(value)
        except ValueError:
            raise FormatError(f"option {key} must be an integer") from None
    return value


def discover():
    """Import every format module in this package (all but private helpers)."""
    names = sorted(m.name for m in pkgutil.iter_modules(__path__) if m.name not in _PRIVATE and not m.name.startswith("_"))
    return [importlib.import_module(f"{__name__}.{name}") for name in names]


REGISTRY = Registry(discover())
FORMATS = {name: REGISTRY.modules[name] for name in REGISTRY.names()}
EXTENSIONS = dict(REGISTRY.extensions)
OUTPUTS = REGISTRY.outputs()


def detect(source, path=None):
    """Pick a format from the file extension, else from the content."""
    return REGISTRY.detect(source, path)


def options(fmt, pairs):
    """Validated options of ``fmt`` from ``key=value`` pairs or a dict."""
    return REGISTRY.options(fmt, pairs)


def extract(source, fmt, opts=None):
    """Return the segments of ``source`` in format ``fmt``."""
    return REGISTRY.module(fmt).extract(source, **options(fmt, opts or {}))


def rebuild(source, fmt, rewritten, opts=None):
    """Return ``source`` with segments replaced by ``rewritten`` (``{id: text}``)."""
    return REGISTRY.module(fmt).rebuild(source, rewritten, **options(fmt, opts or {}))


__all__ = ["EXTENSIONS", "FORMATS", "OUTPUTS", "REGISTRY", "FormatError", "Registry", "detect", "discover",
           "extract", "options", "public", "rebuild"]
