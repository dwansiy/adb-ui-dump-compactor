# ADB UI Dump Compactor

`adb shell uiautomator dump` XML을 LLM 테스트 자동화에 맞게 작게 줄이는 Python 도구입니다.
기본 목표는 "화면 이해와 액션 결정에 필요한 정보만 남기기"입니다.

## 핵심 아이디어

- XML 태그/속성명을 제거하고 한 줄 포맷으로 변환합니다.
- `package`, `resource-id`, `content-desc`, `text`, class, 좌표, 액션 상태를 기본 보존합니다.
- `android.widget.Button`은 `Button`, `com.app:id/login`은 `login`처럼 줄입니다.
- boolean 속성은 `f=CSD...` 같은 flag 문자열로 합칩니다.
- `bounds="[0,0][100,80]"`는 기본적으로 중심점 `p=50,40`만 남깁니다.
- 클릭 가능한 부모 안의 자식 텍스트를 부모 한 줄로 접습니다.
- 반복 화면에서는 `diff` 명령으로 이전 dump 대비 추가/삭제만 보낼 수 있습니다.

## 빠른 사용

```powershell
python .\uidump_compactor.py compact .\window.xml
```

stdin 파이프:

```powershell
adb shell uiautomator dump /sdcard/window.xml
adb shell cat /sdcard/window.xml | python .\uidump_compactor.py compact -
```

출력 예:

```text
1|2|LinearLayout|pkg=com.example|id=login_row|t="Sign in"|p=540,620|f=C
1|5|EditText|pkg=com.example|id=email|t="Email"|p=540,780|f=F
1|8|Button|pkg=com.example|id=submit|t="Continue"|p=540,930|f=C
```

line schema:

```text
depth|source_index|Class|key=value|key=value|f=FLAGS
```

flag legend:

```text
C clickable, L long-clickable, S scrollable, K checkable, X checked,
T selected, F focusable, O focused, P password, D disabled
```

## 프리셋

```powershell
python .\uidump_compactor.py compact .\window.xml --preset llm
python .\uidump_compactor.py compact .\window.xml --preset extreme
python .\uidump_compactor.py compact .\window.xml --preset debug
```

- `llm`: 기본값. 테스트 자동화용 의미 정보만 남깁니다.
- `extreme`: 텍스트 길이를 더 줄이고 최소 신호만 남깁니다.
- `debug`: 거의 모든 노드를 남기되 속성명은 줄입니다.

## 필요한 속성만 선택

```powershell
python .\uidump_compactor.py compact .\window.xml --attrs class,package,text,resource-id,bounds,clickable,enabled
```

alias도 사용할 수 있습니다.

```powershell
python .\uidump_compactor.py compact .\window.xml --attrs c,pkg,t,id,b,clk,en
```

## 좌표 압축

```powershell
python .\uidump_compactor.py compact .\window.xml --coords center
python .\uidump_compactor.py compact .\window.xml --coords bounds
python .\uidump_compactor.py compact .\window.xml --coords both
python .\uidump_compactor.py compact .\window.xml --coords none
```

기본값은 `center`입니다. 실제 tap 자동화에는 보통 중심점만으로 충분합니다.

## JSON/NDJSON 출력

```powershell
python .\uidump_compactor.py compact .\window.xml --format json
python .\uidump_compactor.py compact .\window.xml --format ndjson
```

API나 후처리 파이프라인에서는 `json`이 더 다루기 쉽습니다.
LLM에게 직접 보여줄 때는 기본 `lines`가 보통 더 짧습니다.

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

## Diff로 반복 토큰 줄이기

같은 화면 흐름에서 매번 전체 dump를 보내지 말고, 이전 dump와 현재 dump의 변화만 보낼 수 있습니다.

```powershell
python .\uidump_compactor.py diff .\before.xml .\after.xml
```

## 권장 프롬프트 방식

LLM system/developer prompt에는 한 번만 line schema와 flag legend를 알려두고,
각 step에는 `--header` 없이 compact 결과만 보내는 편이 토큰 효율이 좋습니다.

예:

```text
다음 UI dump는 uxd-v1 형식이다.
각 줄은 depth|source_index|Class|key=value... 이다.
p=x,y는 tap 중심점이고 pkg는 Android package이며 f=C는 clickable, S는 scrollable, D는 disabled다.
목표를 달성하기 위한 다음 adb 액션을 JSON으로 반환하라.
```

## 테스트

```powershell
python -m unittest discover -s tests
```
