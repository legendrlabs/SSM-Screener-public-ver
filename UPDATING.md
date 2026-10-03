# SSM 업데이트

## v1.1.3 이상

현재 설치 버전과 최신 공개 release를 확인합니다.

```bash
ssm version
```

업데이트가 있으면 아래 명령으로 갱신합니다.

```bash
ssm update
```

실제 변경 없이 업데이트 방식만 확인하려면:

```bash
ssm update --dry-run
```

v1.1.3부터 updater는 최신 GitHub Release의 `release.json`을 먼저 읽어 release version과 immutable source commit을 확정합니다. 그 뒤 해당 commit archive만 내려받고 project version, source commit, managed-file SHA-256을 검증한 뒤 업데이트를 적용합니다. 검증이 하나라도 실패하면 기존 설치를 변경하지 않습니다.

업데이트 시 다음 사용자 상태는 보존합니다.

- `config/watchlist.csv`
- `config/overrides.json`
- `output/`
- 환경변수 `SEC_USER_AGENT`

번들 파일 교체 도중 오류가 발생하면 새로 만든 파일을 제거하고 덮어쓴 파일을 기존 상태로 복구합니다.

Git checkout 설치본은 unpinned `git pull`을 사용하지 않습니다. 로컬 변경이 없는 경우 manifest가 지정한 source commit을 fetch한 뒤 fast-forward-only로 적용합니다. 안전하게 이동할 수 없는 checkout은 강제로 덮어쓰지 않고 업데이트를 중단합니다.

`scan`/`check` 실행 때 새 버전이 확인되면 업데이트 안내만 표시하며, 강제로 갱신하지 않습니다.

## v1.1.2에서 v1.1.3으로 올라오는 경우

v1.1.2에는 release-manifest updater가 아직 없으므로 **이번 한 번만 기존 v1.1.2 updater 경로**를 이용해 v1.1.3으로 올라옵니다.

```bash
ssm update
```

v1.1.3 설치가 완료된 뒤부터는 이후 버전을 immutable release manifest + commit-pinned archive 방식으로 업데이트합니다.

## v1.1.1 이하에서 처음 올라오는 경우

v1.1.1 이하에는 updater 자체가 없으므로 한 번 재설치가 필요합니다.

Python/pip 설치본:

```bash
python -m pip install --upgrade https://github.com/legendrlabs/SSM-Screener-public-ver/archive/refs/heads/main.zip
```

ChatGPT/Codex 스킬 번들로 설치한 경우에는 `legendrlabs/SSM-Screener-public-ver`에서 스킬을 한 번 재설치합니다. 최신 버전으로 올라온 뒤에는 `ssm update`를 사용할 수 있습니다.
