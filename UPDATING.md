# SSM 업데이트

## CLI 안정화 v1.1.7 — Work/Codex 격리 실행

- `python "<SKILL_DIR>/scripts/run_ssm.py" --help`: Python 3.11+만으로 동작하며 SEC/시장 모듈을 import하지 않습니다.
- `python "<SKILL_DIR>/scripts/run_ssm.py" version --offline`: 외부 패키지·네트워크 없이 로컬 버전 확인. `check_error=OFFLINE_CHECK_SKIPPED`와 `update_available=null`은 조회 생략을 의미합니다.
- 온라인 `version`: GitHub Release `release.json`을 표준 라이브러리로 검사합니다. HTTP 요청별 8초 타임아웃과 일시적인 오류에 한 번 재시도를 적용하며, 실패 시 `latest=null`, `update_available=null`, `check_error`를 반환합니다. `false`는 성공적으로 비교 후 업데이트가 없는 경우에만 사용합니다.
- 기본 Python에 스캔 의존성이 없으면 기존 스킬을 변경하지 말고 `python "<SKILL_DIR>/scripts/prepare_runtime.py" --venv "<TASK_DIR>/.ssm-venv"`를 실행합니다. 출력된 격리 Python으로 `scan`/`check`를 수행합니다. PyPI 접근이 실패하면 별도로 보고하고 작업을 중단합니다.
- `update`와 `scan`은 의존성 설치와 다른 단계입니다. 업데이트는 명시적 사용자 승인 후 실행하며 설치본 Git/번들·무결성 및 개인 설정 보존 정책은 변하지 않습니다. 이미 설치한 Work 스킬이 GitHub 릴리스로 자동 교체되는 것은 아닙니다.


## 최신 배포 v1.1.6 — 사용자별 SEC 설정

v1.1.6은 배포 전용 정책을 정식 릴리스에 반영합니다. 중앙 SEC 자동 스캔과 원본 저장소의 결과 게시 워크플로는 제거되어, 설치자마다 **자신의 실행 환경에서** 연락 가능한 이름·이메일로 `SEC_USER_AGENT`를 설정합니다. 이 값은 SEC 로그인 비밀번호나 API 키가 아닌 요청자 연락처이며, 공개 코드나 릴리스에 포함하지 않습니다.

업데이트 시 개인 `config/watchlist.csv`, `config/overrides.json`, `output/`, 기존 프로세스 환경변수 `SEC_USER_AGENT`는 보존합니다. 정상적인 설치본에서는 새 버전을 확인하고 `ssm update`로 반영하세요. `version`과 `--help`는 SEC 연락처 없이 확인할 수 있지만, `scan`과 `check`에는 각 사용자 자신의 연락처 및 실시간 네트워크 접근이 필요합니다.

이 공개 저장소에는 중앙 스캔 결과가 없으므로 ChatGPT 스킬이 실제로 연결되지 않은 환경에서는 GitHub의 `output/`을 최신 보고서로 대체하지 않습니다.

## 통합 배포 v1.1.5

업데이트 주소는 기존 `legendrlabs/SSM-Screener-public-ver` 그대로입니다. `SSM-Screener`로 설치 주소를 바꿀 필요가 없습니다. v1.1.2 이상은 `ssm version`으로 확인하고 `ssm update`로 통합 엔진을 받습니다. v1.1.1 이하는 아래 재설치 절차를 사용합니다. Git 설치본에 로컬 변경이 있으면 강제로 덮어쓰지 않고 중단합니다.

이제 이 저장소를 개발·배포 기준으로 사용합니다. 원본 운영 저장소의 watchlist, overrides, 기존 결과나 SEC 연락처 설정을 배포하지 않습니다. GitHub 릴리스에 동봉된 `release.json`이 authoritative manifest이며 저장소 루트의 과거 정적 사본은 제거했습니다.

main의 pyproject.toml 변경은 전체 테스트 후 새 버전 릴리스를 준비합니다. 이미 다른 commit을 가리키는 같은 버전 태그가 있으면 건너뛰며 태그나 공개 asset을 덮어쓰지 않습니다. 태그 push와 수동 태그 배포도 유지합니다.

## v1.1.4 이상

현재 설치 버전과 최신 공개 release를 확인합니다.

```bash
ssm version
```

업데이트가 있으면 직접 아래 명령으로 갱신할 수도 있습니다.

```bash
ssm update
```

실제 변경 없이 업데이트 방식만 확인하려면:

```bash
ssm update --dry-run
```

직접 터미널에서 `ssm scan` 또는 `ssm check ...`를 실행할 때 새 버전이 확인되고 stdin/stderr가 실제 TTY이면 다음처럼 확인합니다.

```text
SSM 1.1.6 available (current 1.1.5). Run: ssm update
Update now? [y/N]:
```

`y` 또는 `yes`로 승인하면 immutable release 검증 경로로 업데이트한 뒤 원래 명령을 새 프로세스로 다시 실행합니다. Enter 또는 그 밖의 응답은 기본적으로 업데이트를 건너뛰고 현재 버전으로 계속합니다. CI, 파이프, 에이전트처럼 비대화형인 환경에서는 터미널 입력을 기다리지 않고 기존 업데이트 안내만 출력합니다.

ChatGPT/Codex 스킬에서는 `scan`/`check` 전에 버전을 먼저 확인합니다. 새 버전이 있으면 채팅에서 자연어로 업데이트 여부를 묻고, `ㅇㅇ`, `ㄱㄱ`, `해줘`, `진행`, `yes`, `go ahead`처럼 명확한 승인 표현이면 업데이트 후 원래 요청을 계속합니다. `y/n` 형식을 강제하지 않습니다. 사용자가 거절하면 현재 버전으로 계속합니다.

업데이트에 실패하면 실패 원인과 계속 사용하는 현재 SSM 버전을 명시합니다. 업데이트 성공으로 가장하지 않으며 기존 설치/rollback 보호 정책은 그대로 유지됩니다.

## v1.1.3 이상 공통 보안 경로

v1.1.3부터 updater는 최신 GitHub Release의 `release.json`을 먼저 읽어 release version과 immutable source commit을 확정합니다. 그 뒤 해당 commit archive만 내려받고 project version, source commit, managed-file SHA-256을 검증한 뒤 업데이트를 적용합니다. 검증이 하나라도 실패하면 기존 설치를 변경하지 않습니다.

업데이트 시 다음 사용자 상태는 보존합니다.

- `config/watchlist.csv`
- `config/overrides.json`
- `output/`
- 환경변수 `SEC_USER_AGENT`

번들 파일 교체 도중 오류가 발생하면 새로 만든 파일을 제거하고 덮어쓴 파일을 기존 상태로 복구합니다.

Git checkout 설치본은 unpinned `git pull`을 사용하지 않습니다. 로컬 변경이 없는 경우 manifest가 지정한 source commit을 fetch한 뒤 fast-forward-only로 적용합니다. 안전하게 이동할 수 없는 checkout은 강제로 덮어쓰지 않고 업데이트를 중단합니다.

## v1.1.3에서 v1.1.4로 올라오는 경우

v1.1.3에는 immutable updater가 이미 있으므로 아래 명령 한 번으로 v1.1.4에 올라올 수 있습니다.

```bash
ssm update
```

v1.1.4 설치 후부터는 직접 CLI 사용 시 대화형 확인 프롬프트와 ChatGPT/Codex 자연어 업데이트 확인 규칙을 사용할 수 있습니다.

## v1.1.2에서 v1.1.3 이상으로 올라오는 경우

v1.1.2에는 release-manifest updater가 아직 없으므로 **이번 한 번만 기존 v1.1.2 updater 경로**를 이용해 최신 버전으로 올라옵니다.

```bash
ssm update
```

v1.1.3 이상 설치가 완료된 뒤부터는 이후 버전을 immutable release manifest + commit-pinned archive 방식으로 업데이트합니다.

## v1.1.1 이하에서 처음 올라오는 경우

v1.1.1 이하에는 updater 자체가 없으므로 한 번 재설치가 필요합니다.

Python/pip 설치본:

```bash
python -m pip install --upgrade https://github.com/legendrlabs/SSM-Screener-public-ver/archive/refs/heads/main.zip
```

ChatGPT/Codex 스킬 번들로 설치한 경우에는 `legendrlabs/SSM-Screener-public-ver`에서 스킬을 한 번 재설치합니다. 최신 버전으로 올라온 뒤에는 `ssm update`를 사용할 수 있습니다.
