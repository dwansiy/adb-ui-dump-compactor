---
name: adb-ui-dump-compactor
description: Compact Android uiautomator/ADB UI XML dumps into a token-efficient UXD line format for LLM-driven mobile test automation. Use when Codex needs to process, summarize, diff, or provide another AI with `adb shell uiautomator dump` XML, large Android UI hierarchy dumps, action selection context, or tap/type/scroll target discovery without sending full XML.
---

# ADB UI Dump Compactor

Use this skill to turn verbose Android UIAutomator XML into a compact, LLM-readable UI state. Prefer the bundled script over ad hoc XML parsing.

Bundled script:

```text
scripts/uidump_compactor.py
```

## Workflow

1. Read or obtain the UI dump XML. For a live device, use `adb shell uiautomator dump /sdcard/window.xml` and then read it with `adb shell cat /sdcard/window.xml`.
2. Run the bundled compactor with `compact` for the current screen.
3. Use `stats` when the user asks about compression ratio or token savings.
4. Use `diff` for repeated automation loops so the next AI step receives only UI changes when possible.
5. When forwarding compact output to another AI, include the UXD v1 schema below once, then send only compact lines in later turns.

Example commands from the skill directory:

```powershell
python .\scripts\uidump_compactor.py compact .\window.xml
python .\scripts\uidump_compactor.py compact .\window.xml --preset extreme
python .\scripts\uidump_compactor.py compact .\window.xml --format json
python .\scripts\uidump_compactor.py stats .\window.xml
python .\scripts\uidump_compactor.py diff .\before.xml .\after.xml
python .\scripts\uidump_compactor.py serve --host 127.0.0.1 --port 8765
```

If `python` is unavailable, use the environment's available Python executable and pass the same script path.

## UXD V1 Line Format

Default output format:

```text
depth|source_index|Class|key=value|key=value|f=FLAGS
```

Minimal interpretation:

- `depth`: compact tree depth after pruning/folding.
- `source_index`: original XML node order, useful for traceability.
- `Class`: shortened Android class name, for example `Button`, `EditText`, `LinearLayout`.
- `pkg`: Android package name, useful when app, system UI, keyboard, or WebView nodes are mixed.
- `id`: shortened `resource-id` tail, for example `login_button`.
- `t`: visible text.
- `d`: `content-desc`, omitted when equal to `t`.
- `p`: tap center point as `x,y`.
- `b`: full bounds as `x1,y1,x2,y2` when requested.
- `f`: action/state flags.

Flag legend:

```text
C clickable
L long-clickable
S scrollable
K checkable
X checked
T selected
F focusable
O focused
P password
D disabled
```

Values with spaces or special characters may be JSON-quoted. Treat quoted values as strings, not as syntax to show to the mobile user.

Example:

```text
0|1|LinearLayout|pkg=com.example|id=login_row|t="Sign in | Use your account"|p=540,620|f=CF
0|4|EditText|pkg=com.example|id=email|t=Email|p=540,810|f=CF
0|5|Button|pkg=com.example|id=submit|t=Continue|p=540,960|f=CFD
```

Interpretation:

- First row is a clickable/focusable layout whose child labels were folded into `t`.
- Second row is a focusable/clickable text input centered at `540,810`.
- Third row is a clickable/focusable but disabled button.

For the full key list, presets, API shape, and prompt handoff snippet, read `references/uxd-v1-format.md`.

## Presets

- `llm`: default. Keep package, action-relevant state, text, descriptions, ids, class, and center points.
- `extreme`: smaller text and fewer state fields for tight token budgets.
- `debug`: preserve more nodes and full-ish state for troubleshooting.

Use `--attrs` to keep only selected fields:

```powershell
python .\scripts\uidump_compactor.py compact .\window.xml --attrs class,package,text,resource-id,bounds,clickable,enabled
```

Aliases are accepted:

```powershell
python .\scripts\uidump_compactor.py compact .\window.xml --attrs c,pkg,t,id,b,clk,en
```

## Automation Guidance

For tap/type selection, prefer nodes with `C`, `F`, `S`, or input-like classes. Use `p=x,y` as the tap target unless the user explicitly needs raw bounds.

For assertions, prefer stable `pkg`, `id`, `t`, and `d` fields over coordinates.

For long-running test agents, keep the UXD schema in system/developer context once, then send only compact output and the user's goal each step.

For repeated states, consider:

```powershell
python .\scripts\uidump_compactor.py diff .\previous.xml .\current.xml
```

If a compact dump seems to hide needed nodes, rerun with `--preset debug`, `--prune none`, or add explicit `--attrs`.
