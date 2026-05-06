# UXD v1 Format Reference

Use this reference when exact UXD parsing, prompt handoff, or field selection matters.

## Purpose

UXD v1 is a compact intermediate representation for Android UIAutomator XML dumps. It is designed for LLM-driven test automation, where the model usually needs actionable UI state rather than lossless XML.

Default line schema:

```text
depth|source_index|Class|key=value|key=value|f=FLAGS
```

Machine-readable JSON schema:

```json
{
  "v": "1.0",
  "schema": ["depth", "n", "attrs"],
  "nodes": [[0, 5, {"c": "Button", "pkg": "com.example", "id": "submit", "t": "Continue", "p": "540,960", "f": "CFD"}]]
}
```

## Positional Columns

| Column | Meaning |
| --- | --- |
| `depth` | Tree depth after pruning and folding. It is not necessarily the original XML depth. |
| `source_index` | Original XML traversal index. Use for traceability/debugging. |
| `Class` | Short class name from XML `class`, usually the final Java/Kotlin segment. |

## Compact Keys

| Key | Original XML field | Meaning |
| --- | --- | --- |
| `ix` | `index` | Original sibling index. Usually omitted. |
| `c` | `class` | Class name. In line format it appears as the third positional field. |
| `pkg` | `package` | Android package name. |
| `id` | `resource-id` | Shortened id tail by default, for example `com.app:id/login` -> `login`. |
| `t` | `text` | Visible text, whitespace-normalized and length-limited. |
| `d` | `content-desc` | Accessibility description. Omitted when identical to `t`. |
| `p` | `bounds` | Center point `x,y`, derived from `[x1,y1][x2,y2]`. |
| `b` | `bounds` | Full rectangle `x1,y1,x2,y2` when `--coords bounds` or `both` is used. |
| `f` | boolean attrs | Packed action/state flags. |
| `naf` | `NAF` | Not Accessibility Friendly marker when requested. |

## Flags

| Flag | Original XML field | Meaning |
| --- | --- | --- |
| `C` | `clickable=true` | Node can be tapped/clicked. |
| `L` | `long-clickable=true` | Node supports long press. |
| `S` | `scrollable=true` | Node can be scrolled. |
| `K` | `checkable=true` | Node supports checked state. |
| `X` | `checked=true` | Node is checked. |
| `T` | `selected=true` | Node is selected. |
| `F` | `focusable=true` | Node can receive focus. |
| `O` | `focused=true` | Node currently has focus. |
| `P` | `password=true` | Node is a password field. |
| `D` | `enabled=false` | Node is disabled. |

## Presets

`llm`:

- Keeps class, package, id, text, content-desc, center point, and common action/state booleans.
- Prunes empty/non-actionable nodes.
- Folds descendant labels into actionable parent nodes.
- Best default for LLM action planning.

`extreme`:

- Similar to `llm`, but limits text more aggressively and keeps fewer state details.
- Use when token budget is extremely tight.

`debug`:

- Keeps more fields and does not fold/prune as aggressively.
- Use when the compact output hides something needed.

## Folding Behavior

When a node is actionable and its descendants are only labels, descendant text and descriptions are merged into the parent:

```text
0|1|LinearLayout|pkg=com.example|id=login_row|t="Sign in | Use your account"|p=540,620|f=CF
```

This means a single row may represent an actionable container plus its child labels. For automation, tap the parent `p` coordinate.

## Pruning Behavior

The default `actionable` pruning keeps nodes that are clickable, long-clickable, scrollable, checkable, input-like, disabled, or have meaningful identity/text/description. Pure layout and empty decorative nodes are dropped.

If required nodes are missing, rerun with:

```powershell
python .\scripts\uidump_compactor.py compact .\window.xml --preset debug
python .\scripts\uidump_compactor.py compact .\window.xml --prune none
python .\scripts\uidump_compactor.py compact .\window.xml --attrs class,package,resource-id,text,content-desc,bounds,clickable,enabled
```

## Command Reference

Compact:

```powershell
python .\scripts\uidump_compactor.py compact .\window.xml
```

Compact from stdin:

```powershell
adb shell cat /sdcard/window.xml | python .\scripts\uidump_compactor.py compact -
```

Stats:

```powershell
python .\scripts\uidump_compactor.py stats .\window.xml
```

Diff:

```powershell
python .\scripts\uidump_compactor.py diff .\before.xml .\after.xml
```

HTTP API:

```powershell
python .\scripts\uidump_compactor.py serve --host 127.0.0.1 --port 8765
```

`POST /compact` accepts raw XML or JSON:

```json
{
  "xml": "<hierarchy>...</hierarchy>",
  "preset": "llm",
  "format": "json",
  "attrs": ["class", "package", "text", "resource-id", "bounds", "clickable"]
}
```

## Prompt Handoff Snippet

Use this once when sending UXD lines to another AI:

```text
The following Android UI dump uses UXD v1 compact format.
Each line is: depth|source_index|Class|key=value...
Important keys: pkg=Android package, id=resource-id tail, t=visible text, d=content-desc, p=tap center x,y, b=bounds x1,y1,x2,y2, f=flags.
Flags: C clickable, L long-clickable, S scrollable, K checkable, X checked, T selected, F focusable, O focused, P password, D disabled.
Choose the next Android test action using stable package/id/text/descriptions first and p coordinates for tap targets.
Return the action as JSON.
```

Then provide compact output:

```text
0|1|LinearLayout|pkg=com.example|id=login_row|t="Sign in | Use your account"|p=540,620|f=CF
0|4|EditText|pkg=com.example|id=email|t=Email|p=540,810|f=CF
0|5|Button|pkg=com.example|id=submit|t=Continue|p=540,960|f=CFD
```

## Output Selection Guidance

Use `lines` for direct LLM prompts because it is shortest.

Use `json` when another program will parse the result.

Use `ndjson` for streaming pipelines or logs.

Use `--coords center` for taps. Use `--coords bounds` only when gestures, hitbox checks, or visual layout reasoning need rectangles.
