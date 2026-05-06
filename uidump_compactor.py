#!/usr/bin/env python3
"""Compact Android uiautomator XML dumps for LLM-based test automation.

The default output is a small line-oriented format:

    depth|source_index|Class|key=value|key=value|f=FLAGS

It intentionally keeps enough semantics for an agent to decide where to tap,
type, scroll, or assert, while avoiding the XML verbosity that burns tokens.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


VERSION = "1.0"

TEXT_ATTRS = ("text", "content-desc")
BOOL_ATTRS = (
    "clickable",
    "long-clickable",
    "scrollable",
    "checkable",
    "checked",
    "selected",
    "focusable",
    "focused",
    "password",
    "enabled",
)

FULL_TO_ALIAS = {
    "index": "ix",
    "text": "t",
    "resource-id": "id",
    "class": "c",
    "package": "pkg",
    "content-desc": "d",
    "bounds": "b",
    "clickable": "clk",
    "long-clickable": "lclk",
    "scrollable": "scr",
    "checkable": "chkable",
    "checked": "chk",
    "selected": "sel",
    "focusable": "foc",
    "focused": "focd",
    "password": "pwd",
    "enabled": "en",
    "NAF": "naf",
}

ALIAS_TO_FULL = {v: k for k, v in FULL_TO_ALIAS.items()}
ALIAS_TO_FULL.update(
    {
        "desc": "content-desc",
        "rid": "resource-id",
        "res": "resource-id",
        "cls": "class",
        "long": "long-clickable",
        "scroll": "scrollable",
    }
)

FLAG_CHARS = {
    "clickable": "C",
    "long-clickable": "L",
    "scrollable": "S",
    "checkable": "K",
    "checked": "X",
    "selected": "T",
    "focusable": "F",
    "focused": "O",
    "password": "P",
}

DEFAULT_PRESETS = {
    "llm": {
        "attrs": [
            "class",
            "package",
            "resource-id",
            "text",
            "content-desc",
            "bounds",
            "clickable",
            "long-clickable",
            "scrollable",
            "checkable",
            "checked",
            "selected",
            "focusable",
            "focused",
            "password",
            "enabled",
        ],
        "coords": "center",
        "prune": "actionable",
        "fold_actionable": True,
        "short_class": True,
        "short_id": True,
        "bool_mode": "flags",
        "max_text": 120,
    },
    "extreme": {
        "attrs": [
            "class",
            "package",
            "resource-id",
            "text",
            "content-desc",
            "bounds",
            "clickable",
            "long-clickable",
            "scrollable",
            "checkable",
            "checked",
            "password",
            "enabled",
        ],
        "coords": "center",
        "prune": "actionable",
        "fold_actionable": True,
        "short_class": True,
        "short_id": True,
        "bool_mode": "flags",
        "max_text": 80,
    },
    "debug": {
        "attrs": [
            "index",
            "class",
            "package",
            "resource-id",
            "text",
            "content-desc",
            "bounds",
            "clickable",
            "long-clickable",
            "scrollable",
            "checkable",
            "checked",
            "selected",
            "focusable",
            "focused",
            "password",
            "enabled",
            "NAF",
        ],
        "coords": "bounds",
        "prune": "none",
        "fold_actionable": False,
        "short_class": True,
        "short_id": False,
        "bool_mode": "flags",
        "max_text": 240,
    },
}

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.,/:\[\]@+-]+$")
BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass
class Options:
    preset: str = "llm"
    attrs: List[str] = field(default_factory=list)
    output_format: str = "lines"
    coords: str = "center"
    prune: str = "actionable"
    fold_actionable: bool = True
    short_class: bool = True
    short_id: bool = True
    bool_mode: str = "flags"
    max_text: int = 120
    header: bool = False
    include_regex: Optional[str] = None
    exclude_regex: Optional[str] = None


@dataclass
class Node:
    source_index: int
    attrs: Dict[str, str]
    children: List["Node"] = field(default_factory=list)


@dataclass
class Record:
    depth: int
    source_index: int
    attrs: Dict[str, Any]
    raw_attrs: Dict[str, str]


@dataclass
class CompactResult:
    records: List[Record]
    raw_bytes: int
    out_bytes: int
    nodes_in: int
    nodes_out: int
    output: str

    @property
    def reduction_pct(self) -> float:
        if self.raw_bytes <= 0:
            return 0.0
        return 100.0 * (1.0 - (self.out_bytes / self.raw_bytes))


def canonical_attr(name: str) -> str:
    trimmed = name.strip()
    return ALIAS_TO_FULL.get(trimmed, trimmed)


def split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def bool_value(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def parse_bounds(value: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    if not value:
        return None
    match = BOUNDS_RE.fullmatch(value.strip())
    if not match:
        return None
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def format_bounds(bounds: Tuple[int, int, int, int]) -> str:
    return f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"


def format_center(bounds: Tuple[int, int, int, int]) -> str:
    x1, y1, x2, y2 = bounds
    return f"{(x1 + x2) // 2},{(y1 + y2) // 2}"


def short_class_name(value: str) -> str:
    if not value:
        return value
    parts = value.split(".")
    return parts[-1] if parts else value


def short_resource_id(value: str) -> str:
    if not value:
        return value
    if ":id/" in value:
        return value.rsplit(":id/", 1)[-1]
    if "/" in value:
        return value.rsplit("/", 1)[-1]
    return value


def clean_text(value: str, max_text: int) -> str:
    compact = " ".join(value.split())
    if max_text > 0 and len(compact) > max_text:
        return compact[: max_text - 1].rstrip() + "~"
    return compact


def quote_value(value: Any) -> str:
    text = str(value)
    if text == "":
        return '""'
    if SAFE_TOKEN_RE.fullmatch(text):
        return text
    return json.dumps(text, ensure_ascii=False, separators=(",", ":"))


def parse_xml(xml_text: str) -> Tuple[Node, int]:
    root_el = ET.fromstring(xml_text)
    counter = 0

    def convert(element: ET.Element) -> Node:
        nonlocal counter
        current = Node(source_index=counter, attrs=dict(element.attrib))
        counter += 1
        current.children = [convert(child) for child in list(element) if child.tag == "node"]
        return current

    if root_el.tag == "node":
        return convert(root_el), counter

    node_children = [child for child in list(root_el) if child.tag == "node"]
    virtual_root = Node(source_index=-1, attrs={"class": root_el.tag})
    virtual_root.children = [convert(child) for child in node_children]
    return virtual_root, counter


def is_true(attrs: Dict[str, str], attr: str) -> bool:
    return bool_value(attrs.get(attr)) is True


def is_false(attrs: Dict[str, str], attr: str) -> bool:
    return bool_value(attrs.get(attr)) is False


def has_text_signal(attrs: Dict[str, str]) -> bool:
    return any(clean_text(attrs.get(attr, ""), 10**9) for attr in TEXT_ATTRS)


def is_input_class(attrs: Dict[str, str]) -> bool:
    cls = attrs.get("class", "")
    return cls.endswith("EditText") or "Input" in cls


def is_actionable(attrs: Dict[str, str]) -> bool:
    return (
        is_true(attrs, "clickable")
        or is_true(attrs, "long-clickable")
        or is_true(attrs, "scrollable")
        or is_true(attrs, "checkable")
        or is_input_class(attrs)
    )


def has_identity_signal(attrs: Dict[str, str]) -> bool:
    return bool(attrs.get("resource-id")) or bool(attrs.get("content-desc")) or has_text_signal(attrs)


def gather_descendant_labels(node: Node, max_text: int) -> Tuple[List[str], List[str]]:
    texts: List[str] = []
    descs: List[str] = []

    def walk(current: Node) -> None:
        text = clean_text(current.attrs.get("text", ""), max_text)
        desc = clean_text(current.attrs.get("content-desc", ""), max_text)
        if text:
            texts.append(text)
        if desc and desc != text:
            descs.append(desc)
        for child in current.children:
            walk(child)

    for child in node.children:
        walk(child)
    return dedupe_keep_order(texts), dedupe_keep_order(descs)


def dedupe_keep_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def text_for_filter(attrs: Dict[str, Any]) -> str:
    return " ".join(str(value) for value in attrs.values() if value is not None)


def build_record_attrs(node: Node, options: Options) -> Dict[str, Any]:
    wanted = set(options.attrs)
    raw = node.attrs
    out: Dict[str, Any] = {}

    if "class" in wanted and raw.get("class"):
        out["c"] = short_class_name(raw["class"]) if options.short_class else raw["class"]
    if "package" in wanted and raw.get("package"):
        out["pkg"] = raw["package"]
    if "index" in wanted and raw.get("index") not in (None, ""):
        out["ix"] = raw["index"]
    if "resource-id" in wanted and raw.get("resource-id"):
        out["id"] = short_resource_id(raw["resource-id"]) if options.short_id else raw["resource-id"]

    text = clean_text(raw.get("text", ""), options.max_text)
    desc = clean_text(raw.get("content-desc", ""), options.max_text)
    if options.fold_actionable and is_actionable(raw):
        child_texts, child_descs = gather_descendant_labels(node, options.max_text)
        if child_texts:
            merged = dedupe_keep_order(([text] if text else []) + child_texts)
            text = clean_text(" | ".join(merged), options.max_text)
        if child_descs:
            merged_desc = dedupe_keep_order(([desc] if desc else []) + child_descs)
            desc = clean_text(" | ".join(merged_desc), options.max_text)

    if "text" in wanted and text:
        out["t"] = text
    if "content-desc" in wanted and desc and desc != text:
        out["d"] = desc

    bounds = parse_bounds(raw.get("bounds"))
    if bounds and "bounds" in wanted:
        if options.coords == "center":
            out["p"] = format_center(bounds)
        elif options.coords == "bounds":
            out["b"] = format_bounds(bounds)
        elif options.coords == "both":
            out["p"] = format_center(bounds)
            out["b"] = format_bounds(bounds)

    if options.bool_mode == "flags":
        flags = ""
        for attr, flag in FLAG_CHARS.items():
            if attr in wanted and is_true(raw, attr):
                flags += flag
        if "enabled" in wanted and is_false(raw, "enabled"):
            flags += "D"
        if flags:
            out["f"] = flags
    elif options.bool_mode == "attrs":
        for attr in BOOL_ATTRS:
            if attr not in wanted:
                continue
            value = bool_value(raw.get(attr))
            if value is True:
                out[FULL_TO_ALIAS[attr]] = 1
            elif attr == "enabled" and value is False:
                out[FULL_TO_ALIAS[attr]] = 0

    if "NAF" in wanted and raw.get("NAF"):
        out["naf"] = raw["NAF"]

    return out


def should_keep(node: Node, record_attrs: Dict[str, Any], options: Options) -> bool:
    if node.source_index < 0:
        return False
    if options.prune == "none":
        return True
    if options.prune == "empty":
        without_position = {k: v for k, v in record_attrs.items() if k not in ("p", "b", "c")}
        return bool(without_position)
    if options.prune == "actionable":
        raw = node.attrs
        return (
            is_actionable(raw)
            or has_identity_signal(raw)
            or is_false(raw, "enabled")
            or bool(record_attrs.get("naf"))
        )
    raise ValueError(f"Unknown prune mode: {options.prune}")


def child_is_folded_label(parent: Node, child: Node, options: Options) -> bool:
    if not options.fold_actionable or not is_actionable(parent.attrs):
        return False
    if subtree_has_actionable_or_resource_id(child):
        return False
    return subtree_has_label(child)


def subtree_has_label(node: Node) -> bool:
    if has_text_signal(node.attrs) or bool(node.attrs.get("content-desc")):
        return True
    return any(subtree_has_label(child) for child in node.children)


def subtree_has_actionable_or_resource_id(node: Node) -> bool:
    if is_actionable(node.attrs) or bool(node.attrs.get("resource-id")):
        return True
    return any(subtree_has_actionable_or_resource_id(child) for child in node.children)


def build_records(root: Node, options: Options) -> List[Record]:
    include_re = re.compile(options.include_regex) if options.include_regex else None
    exclude_re = re.compile(options.exclude_regex) if options.exclude_regex else None
    records: List[Record] = []

    def walk(node: Node, depth: int) -> None:
        record_attrs = build_record_attrs(node, options)
        keep = should_keep(node, record_attrs, options)
        if keep:
            haystack = text_for_filter(record_attrs)
            if include_re and not include_re.search(haystack):
                keep = False
            if exclude_re and exclude_re.search(haystack):
                keep = False
        if keep:
            records.append(Record(depth=depth, source_index=node.source_index, attrs=record_attrs, raw_attrs=node.attrs))
            next_depth = depth + 1
        else:
            next_depth = depth
        for child in node.children:
            if keep and child_is_folded_label(node, child, options):
                continue
            walk(child, next_depth)

    walk(root, 0)
    return records


def render_header(result: CompactResult) -> str:
    legend = "f=C clickable,L long,S scroll,K checkable,X checked,T selected,F focusable,O focused,P password,D disabled"
    return (
        f"# uxd-v{VERSION} raw={result.raw_bytes} out={result.out_bytes} "
        f"nodes={result.nodes_in}->{result.nodes_out} reduce={result.reduction_pct:.1f}% {legend}"
    )


def render_lines(records: Sequence[Record], options: Options, stats: Optional[Tuple[int, int, int]] = None) -> str:
    lines: List[str] = []
    if options.header and stats:
        raw_bytes, nodes_in, out_bytes = stats
        reduction = 0.0 if raw_bytes <= 0 else 100.0 * (1.0 - (out_bytes / raw_bytes))
        lines.append(
            f"# uxd-v{VERSION} raw={raw_bytes} out={out_bytes} "
            f"nodes={nodes_in}->{len(records)} reduce={reduction:.1f}%"
        )
    for record in records:
        cls = record.attrs.get("c", "_")
        parts = [str(record.depth), str(record.source_index), quote_value(cls)]
        for key, value in record.attrs.items():
            if key == "c":
                continue
            parts.append(f"{key}={quote_value(value)}")
        lines.append("|".join(parts))
    return "\n".join(lines)


def render_json(records: Sequence[Record], pretty: bool = False) -> str:
    payload = {
        "v": VERSION,
        "schema": ["depth", "n", "attrs"],
        "nodes": [[record.depth, record.source_index, record.attrs] for record in records],
    }
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def render_ndjson(records: Sequence[Record]) -> str:
    return "\n".join(
        json.dumps({"d": record.depth, "n": record.source_index, **record.attrs}, ensure_ascii=False, separators=(",", ":"))
        for record in records
    )


def compact_xml(xml_text: str, options: Options) -> CompactResult:
    ensure_option_defaults(options)
    root, nodes_in = parse_xml(xml_text)
    records = build_records(root, options)
    if options.output_format == "json":
        output = render_json(records, pretty=False)
    elif options.output_format == "pretty-json":
        output = render_json(records, pretty=True)
    elif options.output_format == "ndjson":
        output = render_ndjson(records)
    elif options.output_format == "lines":
        output = render_lines(records, options)
    else:
        raise ValueError(f"Unknown output format: {options.output_format}")
    raw_bytes = len(xml_text.encode("utf-8"))
    out_bytes = len(output.encode("utf-8"))
    if options.output_format == "lines" and options.header:
        for _ in range(3):
            output = render_lines(records, options, stats=(raw_bytes, nodes_in, out_bytes))
            new_out_bytes = len(output.encode("utf-8"))
            if new_out_bytes == out_bytes:
                break
            out_bytes = new_out_bytes
    return CompactResult(
        records=records,
        raw_bytes=raw_bytes,
        out_bytes=out_bytes,
        nodes_in=nodes_in,
        nodes_out=len(records),
        output=output,
    )


def ensure_option_defaults(options: Options) -> None:
    if not options.attrs:
        preset = DEFAULT_PRESETS.get(options.preset, DEFAULT_PRESETS["llm"])
        options.attrs = list(preset["attrs"])


def result_stats(result: CompactResult) -> Dict[str, Any]:
    return {
        "raw_bytes": result.raw_bytes,
        "output_bytes": result.out_bytes,
        "nodes_in": result.nodes_in,
        "nodes_out": result.nodes_out,
        "reduction_pct": round(result.reduction_pct, 2),
    }


def record_signature(record: Record) -> str:
    attrs = record.attrs
    key_parts = [
        str(attrs.get("id", "")),
        str(attrs.get("t", "")),
        str(attrs.get("d", "")),
        str(attrs.get("c", "")),
        str(attrs.get("pkg", "")),
        str(attrs.get("p", attrs.get("b", ""))),
        str(attrs.get("f", "")),
    ]
    return "\u001f".join(key_parts)


def diff_xml(before_xml: str, after_xml: str, options: Options) -> str:
    before = compact_xml(before_xml, options)
    after = compact_xml(after_xml, options)
    before_map = {record_signature(record): record for record in before.records}
    after_map = {record_signature(record): record for record in after.records}
    added = [record for sig, record in after_map.items() if sig not in before_map]
    removed = [record for sig, record in before_map.items() if sig not in after_map]

    lines = [f"# diff added={len(added)} removed={len(removed)}"]
    if added:
        lines.append("+")
        lines.append(render_lines(added, options))
    if removed:
        lines.append("-")
        lines.append(render_lines(removed, options))
    return "\n".join(line for line in lines if line != "")


def read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Optional[str], text: str) -> None:
    if not path or path == "-":
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    Path(path).write_text(text, encoding="utf-8")


def options_from_args(args: argparse.Namespace) -> Options:
    preset_name = getattr(args, "preset", "llm")
    if preset_name not in DEFAULT_PRESETS:
        raise SystemExit(f"Unknown preset '{preset_name}'. Choose: {', '.join(DEFAULT_PRESETS)}")
    preset = DEFAULT_PRESETS[preset_name]
    attrs = [canonical_attr(attr) for attr in split_csv(getattr(args, "attrs", None))]
    if not attrs:
        attrs = list(preset["attrs"])

    coords = getattr(args, "coords", None) or str(preset["coords"])
    prune = getattr(args, "prune", None) or str(preset["prune"])
    bool_mode = getattr(args, "bool_mode", None) or str(preset["bool_mode"])
    max_text = getattr(args, "max_text", None)
    if max_text is None:
        max_text = int(preset["max_text"])

    fold_actionable = bool(preset["fold_actionable"])
    if getattr(args, "fold_actionable", None) is True:
        fold_actionable = True
    if getattr(args, "no_fold_actionable", None) is True:
        fold_actionable = False

    short_class = bool(preset["short_class"])
    if getattr(args, "short_class", None) is True:
        short_class = True
    if getattr(args, "full_class", None) is True:
        short_class = False

    short_id = bool(preset["short_id"])
    if getattr(args, "short_id", None) is True:
        short_id = True
    if getattr(args, "full_id", None) is True:
        short_id = False

    return Options(
        preset=preset_name,
        attrs=attrs,
        output_format=getattr(args, "format", "lines"),
        coords=coords,
        prune=prune,
        fold_actionable=fold_actionable,
        short_class=short_class,
        short_id=short_id,
        bool_mode=bool_mode,
        max_text=max_text,
        header=bool(getattr(args, "header", False)),
        include_regex=getattr(args, "include", None),
        exclude_regex=getattr(args, "exclude", None),
    )


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preset", choices=sorted(DEFAULT_PRESETS), default="llm")
    parser.add_argument("--format", choices=("lines", "json", "pretty-json", "ndjson"), default="lines")
    parser.add_argument("--attrs", help="Comma-separated XML attrs or aliases to keep, e.g. class,package,text,resource-id,bounds,clickable.")
    parser.add_argument("--coords", choices=("center", "bounds", "both", "none"))
    parser.add_argument("--prune", choices=("actionable", "empty", "none"))
    parser.add_argument("--bool-mode", choices=("flags", "attrs", "none"))
    parser.add_argument("--max-text", type=int)
    parser.add_argument("--header", action="store_true", help="Add a one-line stats header to line output.")
    parser.add_argument("--include", help="Keep only records whose compact fields match this regex.")
    parser.add_argument("--exclude", help="Drop records whose compact fields match this regex.")
    parser.add_argument("--fold-actionable", action="store_true", help="Merge descendant labels into actionable parents.")
    parser.add_argument("--no-fold-actionable", action="store_true", help="Do not merge descendant labels into actionable parents.")
    parser.add_argument("--short-class", action="store_true", help="Use final class segment only.")
    parser.add_argument("--full-class", action="store_true", help="Keep full class name.")
    parser.add_argument("--short-id", action="store_true", help="Use resource-id tail only.")
    parser.add_argument("--full-id", action="store_true", help="Keep full resource-id.")


def command_compact(args: argparse.Namespace) -> int:
    options = options_from_args(args)
    xml_text = read_text(args.input)
    result = compact_xml(xml_text, options)
    write_text(args.output, result.output)
    if args.stats:
        print(json.dumps(result_stats(result), ensure_ascii=False), file=sys.stderr)
    return 0


def command_stats(args: argparse.Namespace) -> int:
    options = options_from_args(args)
    xml_text = read_text(args.input)
    result = compact_xml(xml_text, options)
    print(json.dumps(result_stats(result), ensure_ascii=False, indent=2))
    return 0


def command_diff(args: argparse.Namespace) -> int:
    options = options_from_args(args)
    before_xml = read_text(args.before)
    after_xml = read_text(args.after)
    write_text(args.output, diff_xml(before_xml, after_xml, options))
    return 0


class CompactHandler(BaseHTTPRequestHandler):
    server_version = "UidumpCompactor/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"ok": True, "version": VERSION})
            return
        self.send_error(404, "Use POST /compact")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/compact":
            self.send_error(404, "Use POST /compact")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            text_body = body.decode("utf-8")
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                payload = json.loads(text_body)
                xml_text = payload.get("xml", "")
                options = options_from_mapping(payload)
            else:
                xml_text = text_body
                options = options_from_mapping({key: values[-1] for key, values in query.items()})
            result = compact_xml(xml_text, options)
        except Exception as exc:  # pragma: no cover - HTTP guardrail
            self.send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if options.output_format in ("json", "pretty-json"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(result.output.encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("X-Raw-Bytes", str(result.raw_bytes))
            self.send_header("X-Output-Bytes", str(result.out_bytes))
            self.send_header("X-Reduction-Pct", f"{result.reduction_pct:.2f}")
            self.end_headers()
            self.wfile.write(result.output.encode("utf-8"))

    def send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def options_from_mapping(mapping: Dict[str, Any]) -> Options:
    class Args:
        pass

    args = Args()
    preset = mapping.get("preset", "llm")
    setattr(args, "preset", preset)
    fmt = mapping.get("format", mapping.get("output_format", "lines"))
    setattr(args, "format", fmt)
    attrs = mapping.get("attrs")
    if isinstance(attrs, list):
        attrs = ",".join(str(attr) for attr in attrs)
    setattr(args, "attrs", attrs)
    setattr(args, "coords", mapping.get("coords"))
    setattr(args, "prune", mapping.get("prune"))
    setattr(args, "bool_mode", mapping.get("bool_mode", mapping.get("bool-mode")))
    setattr(args, "max_text", int(mapping["max_text"]) if mapping.get("max_text") is not None else None)
    setattr(args, "header", str(mapping.get("header", "false")).lower() in ("1", "true", "yes"))
    setattr(args, "include", mapping.get("include"))
    setattr(args, "exclude", mapping.get("exclude"))
    fold = mapping.get("fold_actionable", mapping.get("fold-actionable"))
    no_fold = mapping.get("no_fold_actionable", mapping.get("no-fold-actionable"))
    setattr(args, "fold_actionable", str(fold).lower() in ("1", "true", "yes") if fold is not None else None)
    setattr(args, "no_fold_actionable", str(no_fold).lower() in ("1", "true", "yes") if no_fold is not None else None)
    setattr(args, "short_class", None)
    setattr(args, "full_class", str(mapping.get("full_class", mapping.get("full-class", "false"))).lower() in ("1", "true", "yes"))
    setattr(args, "short_id", None)
    setattr(args, "full_id", str(mapping.get("full_id", mapping.get("full-id", "false"))).lower() in ("1", "true", "yes"))
    return options_from_args(args)  # type: ignore[arg-type]


def command_serve(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), CompactHandler)
    setattr(server, "quiet", args.quiet)
    print(f"Serving uidump compactor on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compact Android uiautomator XML dumps for LLM test automation.")
    subparsers = parser.add_subparsers(dest="command")

    compact = subparsers.add_parser("compact", help="Compact a dump XML file or stdin.")
    compact.add_argument("input", help="XML file path, or '-' for stdin.")
    compact.add_argument("-o", "--output", help="Output file path. Defaults to stdout.")
    compact.add_argument("--stats", action="store_true", help="Print JSON stats to stderr.")
    add_common_options(compact)
    compact.set_defaults(func=command_compact)

    stats = subparsers.add_parser("stats", help="Show compaction statistics.")
    stats.add_argument("input", help="XML file path, or '-' for stdin.")
    add_common_options(stats)
    stats.set_defaults(func=command_stats)

    diff = subparsers.add_parser("diff", help="Compact and compare two XML dumps.")
    diff.add_argument("before", help="Earlier XML file.")
    diff.add_argument("after", help="Later XML file.")
    diff.add_argument("-o", "--output", help="Output file path. Defaults to stdout.")
    add_common_options(diff)
    diff.set_defaults(func=command_diff)

    serve = subparsers.add_parser("serve", help="Run a small HTTP API. POST raw XML or JSON to /compact.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    serve.add_argument("--quiet", action="store_true")
    serve.set_defaults(func=command_serve)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except ET.ParseError as exc:
        print(f"XML parse error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 141


if __name__ == "__main__":
    raise SystemExit(main())
