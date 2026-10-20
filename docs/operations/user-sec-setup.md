# 사용자별 SEC 연락처 설정 및 SSM 실행

이 저장소 `legendrlabs/SSM-Screener-public-ver`는 **코드·스킬·릴리스 배포와 운영자용 SEC 스캔**을 제공합니다.
운영자 스캔은 Actions 저장소 Secret과 수동/정기 워크플로만 사용하고, 결과를 `main/output/`에 커밋하지 않으며 별도 7일 보존 Actions 아티팩트로 남깁니다.
SSM을 설치한 사람은 계속 **자신의 실행 환경에서** SEC 연락처를 설정하고 실행합니다.

## SEC_USER_AGENT란?

`SEC_USER_AGENT`는 로그인 비밀번호, 개인 API 키 또는 SEC 계정이 아닙니다.
EDGAR 자동 HTTP 요청의 `User-Agent` 헤더에 넣는 이름/단체명과 실제 연락 가능한 이메일입니다.
SEC는 해당 값을 요청에서 보게 됩니다. 이름/이메일은 영문 ASCII 문자로 설정하세요.

개발자는 사용자의 이메일을 추측하거나 임의로 생성하지 않습니다. 배포 패키지에는 기본
연락처 값을 넣지 않고, **미설정 상태에서는 SEC 실시간 호출을 진행하지 않습니다**.

이름·이메일은 이 공개 저장소의 `SKILL.md`, Python 소스, JSON 설정,
`watchlist.csv`, 커밋, 이슈 또는 Pull Request에 넣지 마세요.
ChatGPT 등 대화형 실행 환경에서 직접 설정 기능이 없다면 스킬이 첫 SEC 요청 전에
해당 사용자에게 연락처 입력/환경 설정을 안내해야 합니다. 입력값은 로그에 출력하지 않습니다.

## ChatGPT / Codex 설치

루트의 `SKILL.md`와 `scripts/run_ssm.py`, `ssm/`, `config/`가 포함된
**전체 번들**을 설치합니다. 스킬 설치 폴더는 대화의 `/mnt/data`와 다를 수 있으므로
작업 폴더에서 `scripts/run_ssm.py`를 찾지 말고 **실제 SKILL.md가 있는 폴더**를
기준으로 실행합니다.

1. `python "<SKILL_DIR>/scripts/run_ssm.py" version`과 `--help`로 엔진 확인
2. 첫 `scan`/`check` 실행 전에 `SEC_USER_AGENT` 유무를 **값 출력 없이** 확인
3. 미설정 시 해당 사용자에게 본인 이름/단체명과 수신 가능한 이메일로 설정하도록 안내
4. SEC와 시장 데이터가 실제 수집될 때만 새로운 보고서 작성. 실패하면 `DATA_HOLD`

**GitHub 원본 저장소의 `output/`에는 보고서가 없습니다.**
ChatGPT 스킬이 실행 환경에 제공되지 않는 문제는 GitHub 중앙 결과를 읽는 것으로
대체할 수 없습니다.

## Windows PowerShell (사용자 컴퓨터)

Python 3.11+에서 저장소 ZIP을 직접 푼 뒤 `pyproject.toml`이 있는 폴더에서:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe scripts\run_ssm.py version
.\.venv\Scripts\python.exe scripts\run_ssm.py --help

# 아래 예시를 자신의 실제 연락처로 바꿔서 해당 PowerShell 세션에서만 설정
$env:SEC_USER_AGENT = "Your Name your@email.com"
$env:SSM_SEC_DISCOVERY_MODE = "atom"
.\.venv\Scripts\python.exe scripts\run_ssm.py scan --days 7 --out output
```

## macOS / Linux (사용자 컴퓨터)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python scripts/run_ssm.py version
.venv/bin/python scripts/run_ssm.py --help

# 아래 예시를 자신의 실제 연락처로 바꿔서 현재 터미널 세션에만 설정
export SEC_USER_AGENT="Your Name your@email.com"
export SSM_SEC_DISCOVERY_MODE=atom
.venv/bin/python scripts/run_ssm.py scan --days 7 --out output
```

**주의:** 터미널 히스토리나 호스팅 환경에 연락처가 남을 수 있으니 사용자가
자신의 프라이버시 요구에 맞는 설정 방법을 선택하세요. 공용 로그에 값을 출력하지 마세요.
민감한 실제 거래 포지션과 워치리스트는 사용자별 환경에만 둡니다.

## GitHub Actions를 본인이 쓰고 싶은 경우

이 공개 저장소에는 **유지보수자 전용** `SSM SEC Scan (Manual + Scheduled)` 워크플로가 있습니다.
원본 저장소 운영자는 `Settings > Secrets and variables > Actions`에 `SEC_USER_AGENT`를
Repository Secret으로 한 번 등록해야 합니다. 값은 로그/코드에 출력하거나 보관하지 않습니다.
공개 아티팩트는 7일 보존이며 출처가 공개 SEC인 운영자 기본 설정만 스캔합니다.
사용자별 설치/워치리스트/override를 중앙에서 대신 스캔하는 기능은 아닙니다.

별도 저장소 또는 Fork에서 자동화를 운용하는 사용자는 각자의
`Settings > Secrets and variables > Actions`에 `SEC_USER_AGENT`를 등록해야 합니다.
원본 프로젝트의 Secret은 Fork/설치본으로 공유되지 않습니다.
스크리닝 결과에 개인 관심종목이 포함될 수 있으므로, 공개 Fork에 결과를 커밋하거나
공개 아티팩트로 업로드하지 않는 편이 안전합니다. 본인 저장소의 공개 범위를 확인하세요.

## 구분

- `version`, `--help`: SEC 접속 불필요
- `scan`, `check`: 사용자별 `SEC_USER_AGENT` 및 SEC/시장 네트워크 접근 필요
- 출력: 각 사용자 작업 환경의 `quality.json`, `candidates.csv`,
  `dilution_check.csv`, `event_ledger.csv`, `latest.md`
- 실패 또는 불완전한 희석 자료: `DATA_HOLD`; 검증 없는 `PASS` 금지
