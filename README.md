# ADB UI Dump Compactor

ADB UI Dump Compactor is a Python CLI and HTTP tool that compresses
`adb shell uiautomator dump` XML into a compact format for LLM-driven Android
UI testing and automation.

The default README language is English. A Korean summary is available near the
end of this document.

The main goal is to keep only the information an agent needs to understand the
screen and decide the next action.

## Core Ideas

- Remove verbose XML tags and attribute names, then convert nodes into one-line
  records.
- Preserve the most useful automation signals by default: `package`,
  `resource-id`, `content-desc`, `text`, class name, coordinates, and action
  state.
- Shorten common values, such as `android.widget.Button` to `Button` and
  `com.app:id/login` to `login`.
- Merge boolean attributes into compact flags like `f=CSD...`.
- Convert `bounds="[0,0][100,80]"` to the center point `p=50,40` by default.
- Fold child text into a clickable parent node when that is the more useful
  automation target.
- Use the `diff` command on repeated screens to send only added or removed
  lines compared with a previous dump.

## Quick Start

```powershell
python .\uidump_compactor.py compact .\window.xml
```

Pipe from stdin:

```powershell
adb shell uiautomator dump /sdcard/window.xml
adb shell cat /sdcard/window.xml | python .\uidump_compactor.py compact -
```

Example output:

```text
1|2|LinearLayout|pkg=com.example|id=login_row|t="Sign in"|p=540,620|f=C
1|5|EditText|pkg=com.example|id=email|t="Email"|p=540,780|f=F
1|8|Button|pkg=com.example|id=submit|t="Continue"|p=540,930|f=C
```

Line schema:

```text
depth|source_index|Class|key=value|key=value|f=FLAGS
```

Flag legend:

```text
C clickable, L long-clickable, S scrollable, K checkable, X checked,
T selected, F focusable, O focused, P password, D disabled
```

## Presets

```powershell
python .\uidump_compactor.py compact .\window.xml --preset llm
python .\uidump_compactor.py compact .\window.xml --preset extreme
python .\uidump_compactor.py compact .\window.xml --preset debug
```

- `llm`: Default. Keeps the semantic information needed for test automation.
- `extreme`: Reduces text length further and keeps only the smallest useful
  signal set.
- `debug`: Keeps almost every node while still shortening attribute names.

## Select Attributes

```powershell
python .\uidump_compactor.py compact .\window.xml --attrs class,package,text,resource-id,bounds,clickable,enabled
```

Aliases are also supported:

```powershell
python .\uidump_compactor.py compact .\window.xml --attrs c,pkg,t,id,b,clk,en
```

## Coordinate Compression

```powershell
python .\uidump_compactor.py compact .\window.xml --coords center
python .\uidump_compactor.py compact .\window.xml --coords bounds
python .\uidump_compactor.py compact .\window.xml --coords both
python .\uidump_compactor.py compact .\window.xml --coords none
```

The default is `center`. For tap automation, the center point is usually enough.

## JSON and NDJSON Output

```powershell
python .\uidump_compactor.py compact .\window.xml --format json
python .\uidump_compactor.py compact .\window.xml --format ndjson
```

Use `json` for APIs or post-processing pipelines. Use the default `lines`
format when you want a shorter representation to show directly to an LLM.

## HTTP API

```powershell
python .\uidump_compactor.py serve --host 127.0.0.1 --port 8765
```

Raw XML body:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/compact?preset=llm&format=lines" -InFile .\window.xml -ContentType "text/xml"
```

JSON body:

```json
{
  "xml": "<hierarchy>...</hierarchy>",
  "preset": "llm",
  "format": "json",
  "attrs": ["class", "package", "text", "resource-id", "bounds", "clickable"]
}
```

## Reduce Repeated Tokens With Diff

When a workflow stays on a similar screen, avoid sending the full dump each
time. Send only the changes between the previous dump and the current dump:

```powershell
python .\uidump_compactor.py diff .\before.xml .\after.xml
```

## Recommended Prompting Pattern

Put the line schema and flag legend in the LLM system/developer prompt once.
Then send only the compact output for each step, usually without `--header`.
This keeps token usage low.

Example:

```text
The following UI dump is in uxd-v1 format.
Each line is depth|source_index|Class|key=value...
p=x,y is the tap center point, pkg is the Android package, and f=C means
clickable, S means scrollable, D means disabled.
Return the next adb action as JSON to accomplish the goal.
```

## Tests

```powershell
python -m unittest discover -s tests
```

## Korean Summary

`adb shell uiautomator dump` XML을 LLM 테스트 자동화에 맞게 작게 줄이는
Python 도구입니다. 기본 목표는 화면 이해와 액션 결정에 필요한 정보만
남기는 것입니다.

- XML 태그와 긴 속성명을 제거하고 한 줄 포맷으로 변환합니다.
- `package`, `resource-id`, `content-desc`, `text`, class, 좌표, 액션 상태를
  기본 보존합니다.
- `android.widget.Button`은 `Button`, `com.app:id/login`은 `login`처럼 줄입니다.
- boolean 속성은 `f=CSD...` 같은 flag 문자열로 합칩니다.
- `bounds="[0,0][100,80]"`는 기본적으로 중심점 `p=50,40`만 남깁니다.
- 반복 화면에서는 `diff` 명령으로 이전 dump 대비 변화만 보낼 수 있습니다.

빠른 사용:

```powershell
python .\uidump_compactor.py compact .\window.xml
```

테스트:

```powershell
python -m unittest discover -s tests
```
