# SSM 업데이트

## v1.1.2 이상

현재 버전과 최신 배포판을 확인합니다.

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

`scan`/`check` 실행 때 새 버전이 확인되면 업데이트 안내만 표시하며, 강제로 갱신하지 않습니다.

업데이트 시 다음 사용자 상태는 보존합니다.

- `config/watchlist.csv`
- `config/overrides.json`
- `output/`
- 환경변수 `SEC_USER_AGENT`

업데이트 파일 교체 중 오류가 발생하면 덮어쓴 파일을 기존 상태로 복구합니다.

## v1.1.1 이하에서 처음 올라오는 경우

v1.1.1 이하에는 updater 자체가 없으므로 이번 한 번은 재설치가 필요합니다.

Python/pip 설치본:

```bash
python -m pip install --upgrade https://github.com/legendrlabs/SSM-Screener-public-ver/archive/refs/heads/main.zip
```

ChatGPT/Codex 스킬 번들로 설치한 경우에는 `legendrlabs/SSM-Screener-public-ver`에서 스킬을 한 번 재설치합니다. 그 뒤 v1.1.2 이상부터는 `ssm update`를 사용할 수 있습니다.
