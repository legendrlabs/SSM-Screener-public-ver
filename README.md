# Special Situation Microcap Screener (SSM) v1.1.7

미국 상장 마이크로캡 중 **구조적 재평가 가능성이 있는 특수상황**을 재현 가능한 규칙으로 1차 선별하는 스크리너입니다.

이 저장소는 스킬 배포·업데이트와 운영자 전용 수동/정기 SEC 스캔을 함께 제공합니다. **v1.1.7은 Work/Codex처럼 기본 Python 의존성이 없는 환경을 위한 CLI 경량화·격리 실행환경 준비·업데이트 조회 안정화 릴리스**입니다. v1.1.6은 사용자별 SEC 연락처 설정 정책을 명확히 하고 중앙 스캔/결과 게시를 제거한 릴리스입니다. 스크리닝 엔진의 판정 규칙은 v1.1.5를 유지합니다. v1.1.5는 `SSM-Screener`의 2026-10-18 판정 엔진 변경과 기존 공개 배포본의 설치·업데이트 기능을 합쳤습니다. 기존 v1.1.2 이상 사용자는 `ssm update` 경로를 유지합니다. 원본 운영 저장소의 개인 설정·실행 결과는 옮기지 않았습니다. [통합 내역과 검증 범위](docs/integration/2026-10-19-unification.md)를 참고하세요.

수정·완료 판단은 [v1 안정화 기준](docs/stabilization-policy.md)을 따릅니다. 실전 영향이 있는 오류를 공통 원인 단위로 수정하고, 영향이 없는 세부 표현 차이는 예외 패치 없이 남깁니다.

핵심 원칙:

> **Basic market cap이 아니라 fully diluted economics를 본다.**
>
> **보도자료보다 SEC filing에서 event proof를 확인한다.**
>
> **숫자가 불완전하면 PASS가 아니라 DATA_HOLD다.**


## 배포 및 운영자 SEC 스캔 (개인 설정 분리)

이 공개 저장소는 **스킬 소스·테스트·릴리스 배포**와 **저장소 운영자용 GitHub Actions SEC 스캔**을 제공하지만, 두 실행 경로는 독립적입니다.

- 수동/정기 워크플로: [SSM SEC Scan (Manual + Scheduled)](https://github.com/legendrlabs/SSM-Screener-public-ver/actions/workflows/sec-scan.yml)
- 운영자는 Repository → Settings → Secrets and variables → Actions에 `SEC_USER_AGENT` **repository secret**을 설정해야 합니다. 유효한 ASCII 영문 이름/조직명과 연락 가능한 이메일을 사용하며, **코드·커밋·로그에 표시하지 않습니다.**
- 정기 실행: **월요일 20:30 KST 풀스캔**, **화~금 20:30 KST 증분**, **화~토 07:30 KST 증분**. SEC 접수번호 기반 체크포인트를 사용하며, 오래되거나 검증 실패 시 자동으로 7일 풀스캔으로 전환합니다. GitHub 스케줄은 지연되거나 누락될 수 있습니다.
- 수동 실행: Actions → SSM SEC Scan (Manual + Scheduled) → **Run workflow** → `full`(기본) 또는 `incremental` 선택. 풀스캔 기간은 1/3/7/14/30일 중 선택(기본 7일)하고, 증분은 검증된 최근 체크포인트가 없으면 자동으로 7일 풀스캔으로 복귀합니다.
- Python 3.11 + `requests`/`pandas`/`yfinance`; SEC discovery는 `atom`, 시장 데이터는 `yfinance`; 동일 워크플로의 출력 검증이 성공한 경우에만 완료로 판정합니다.
- 결과는 실행별 `ssm-sec-scan-<run_id>` **GitHub Actions artifact**에 7일간 보관됩니다. 공개 저장소의 Actions 아티팩트는 외부 이용자가 접근할 수 있으므로, 개인 워치리스트·비공개 override·SEC 연락처를 결과에 포함시키지 않습니다.
- **`FULL`과 `INCREMENTAL_DELTA`의 후보 수는 직접 비교하면 안 됩니다.** 증분 결과는 마지막 확인된 SEC 접수번호 이후의 신규 공시와 명시적 워치리스트 검사만 나타내며, 이전 PASS/WATCH 전체를 현재도 유효하다고 보증하지 않습니다. 증분 `latest.md`, `quality.json`, `run_metadata.json`에 검사 범위와 기준 실행 번호를 기록합니다.
- 체크포인트는 과거 정상 실행의 `run_metadata.json` + `seen_filings.json`에서 복원합니다. **최근 성공 결과 36시간, 마지막 7일 이상 풀스캔 7일** 이내일 때만 증분을 허용하고, 누락·손상·조회 실패 시 즉시 전체 스캔으로 바꿉니다. 검사 실패는 PASS로 승격하지 않습니다.
- 결과 파일은 `quality.json`, `latest.md`, `candidates.csv`, `dilution_check.csv`, `event_ledger.csv`, `validation_audit.json`, `run_metadata.json`, `seen_filings.json`입니다. `run_metadata.json`에 실행 번호·소스 커밋·실행 완료 시각·트리거가 저장됩니다.
- `SAFE_TO_ACT=false`/PASS 0/DATA_HOLD는 **정상적으로 끝난 스캔의 분석 판정**일 수 있습니다. 실행 실패와 구분해야 합니다.
- `output/`는 계속 비어 있으며 자동으로 커밋·푸시하지 않습니다. 따라서 `output/quality.json`을 과거 결과로 읽으면 안 됩니다. 새로운 결과는 **같은 실행의 artifact**에서만 읽습니다.
- 배포 사용자들의 SEC 연락처·개인 포트폴리오·설정은 중앙으로 수집되지 않으며, 스킬 설치 후 개인 스캔은 각자의 런타임에서 실행합니다.
- 스케줄 실행은 GitHub-hosted runner 시간과 외부 SEC 요청량을 사용합니다. 같은 날 중복 전체 스캔은 피해야 합니다.

[사용자별 SEC 설정 및 로컬 실행 안내](docs/operations/user-sec-setup.md)를 참고하세요.

## ChatGPT / Codex에서 설치해서 사용하기

스킬 설치와 Python·외부 데이터 조회를 지원하는 환경에서 아래 요청을 붙여넣습니다.

> https://github.com/legendrlabs/SSM-Screener-public-ver 의 SSM 스킬을 설치해줘. 저장소 루트의 SKILL.md와 동봉 실행 코드·설정을 함께 설치하고, 설치 후 실행 진입점과 의존성을 확인해줘.

설치 후에는 다음처럼 요청합니다.

- `SSM으로 최근 7일 미국 주식 특수상황을 점검해줘.`
- `SSM으로 GPRO의 거래대가와 희석 위험을 점검해줘.`
- `SSM으로 LFCR을 점검하고 SEC 원문 링크도 보여줘.`

첫 실제 실행에서 SEC 접속용 이름·이메일 설정을 요청할 수 있습니다. 설치만으로 실제 스캔이 완료되는 것은 아니며, 실행 환경의 Python·네트워크 접근이 필요합니다. ChatGPT/Codex의 설치 기능과 사용 가능 도구는 계정·환경에 따라 다릅니다. 지원되는 환경에서 저장소 전체를 스킬 폴더로 설치해야 합니다.

기본 Python에 `requests`/`pandas`/`yfinance`가 없어도 아래 두 명령은 실행됩니다.

```bash
python "<SKILL_DIR>/scripts/run_ssm.py" --help
python "<SKILL_DIR>/scripts/run_ssm.py" version --offline
```

`version`(오프라인 옵션 없음)은 온라인 최신 릴리스를 확인합니다. 네트워크 조회에 실패하면 `update_available=null`과 `check_error`가 반환되며, 이는 최신 버전이라는 뜻이 아닙니다. 기본 Python에 스캔 의존성이 없는 경우 격리 설치 예시는 다음과 같습니다.

```bash
python "<SKILL_DIR>/scripts/prepare_runtime.py" --venv "<TASK_DIR>/.ssm-venv"
"<TASK_DIR>/.ssm-venv/bin/python" "<SKILL_DIR>/scripts/run_ssm.py" --help
```

Windows에서는 가상환경 Python 경로가 `Scripts/python.exe`입니다. `TASK_DIR`은 쓸 수 있는 별도의 작업 디렉터리이며 `SKILL_DIR` 안에 가상환경을 만들지 않습니다. `prepare_runtime.py`는 실행 의존성만 설치하고 SEC 스캔이나 스킬 등록/업데이트를 수행하지 않습니다. 설치에 필요한 PyPI 네트워크 또는 권한이 없으면 명시적으로 실패를 보고합니다.

실행 진입점은 `scripts/run_ssm.py`입니다. 스킬 설치 폴더와 채팅 작업 폴더가 달라도 동봉 설정을 찾으며, 결과는 지정한 작업 폴더에 저장합니다.

## Python CLI로 직접 설치

Python 3.11 이상이 필요합니다. 이 저장소를 내려받아 압축을 풀거나 clone한 뒤, `pyproject.toml`이 있는 폴더 안에서 실행합니다. 이 배포판은 Python CLI이며 EXE가 아닙니다.

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
$env:SEC_USER_AGENT = "Your Name your@email.com"
$env:SSM_SEC_DISCOVERY_MODE = "atom"
.\.venv\Scripts\ssm.exe scan --days 7 --out output
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
export SEC_USER_AGENT="Your Name your@email.com"
export SSM_SEC_DISCOVERY_MODE=atom
.venv/bin/ssm scan --days 7 --out output
```

SEC_USER_AGENT에는 실제 담당자 이름과 연락 가능한 이메일을 ASCII 문자로 설정합니다. 결과는 `output/latest.md`와 CSV·`quality.json`에 저장됩니다.

`config/watchlist.csv`는 빈 목록이며, 관심 종목은 `config/watchlist.example.csv` 형식으로 직접 입력합니다. 개인 워치리스트·수동 숫자 override·이전 스캔 결과·인증정보는 배포판에 포함하지 않았습니다.

`SKILL.md`는 동봉된 에이전트용 작업 지침입니다. ZIP을 다운로드하거나 CLI를 설치하는 것만으로 ChatGPT 스킬이 자동 설치되지는 않습니다.

v1 안정화는 알려진 실전 영향 오류와 회귀 검증 범위의 안정화를 뜻합니다. 전체 유니버스의 무오류를 보장하지 않습니다. 미확정 경제조건은 DATA_HOLD, 애매한 경우는 SAFE_TO_ACT=FALSE를 유지합니다.

## 찾는 유형

- 사업모델 전환 / 사명·티커 변경 / 역합병
- 사업부 매각 후 신사업 전환
- AI / 데이터센터 / 로봇 / 바이오 / 크립토 등 구조적 pivot
- 현금·증권·토큰·지분·부동산·광물 등 자산가치 대비 할인
- 회사 규모 대비 큰 계약 / 라이선스 / 정부계약 / 전략투자
- 부채 제거 / preferred redemption / refinancing
- low float + 확인 가능한 catalyst
- PIPE / 전략적 투자자가 시장가격과 다른 가격에 참여한 상황
- 8-K / 10-Q에서 확인되는 시장 미반영 변화

## 기본 Gate

`config/default.json`에서 조정합니다.

- 거래소: NASDAQ / NYSE / NYSE American
- 선호 basic MC: $20M ~ $500M
- 확장 universe: $1B 이하
- material event: 최근 60일
- 10-Q/10-K freshness: 210일
- ADV20: $250k 이상 PASS, $50k~250k WATCH, $50k 미만 REJECT
- cap table low confidence: `DATA_HOLD`

## 공시 내용 검증

증자 규모와 함께 자금 사용 목적을 확인합니다. 부채·우선주 상환과 실제 청구권 감소를 원문 근거로 표시하고, authorized shares 증가는 발행 여력으로 분리합니다. `신주/거래 전 보통주` 발행 증가율과 `신주/거래 후 보통주` 기존 주주의 지분 감소율도 구분합니다. 같은 instrument의 전량 소멸·기준 수·시점이 맞아야 중복 FD 항목을 제거합니다.

예정 발행·상환은 완료로 처리하지 않으며, common/pre-funded warrant 배분이나 거래 후 cap table이 불명확하면 DATA_HOLD를 유지합니다. 재자본화 문맥은 희석 경고를 없애거나 PASS로 승격시키지 않습니다. [문맥 추출 및 검증 범위](docs/recapitalization-context.md)를 참고하세요.

최신 10-Q/10-K의 자본구조·subsequent events 및 관련 자금사용 문맥도 read-only로 보완 검토합니다. 명시적인 거래 날짜·증권·금액·전량/부분 상환 결과와 financing 연결이 맞을 때만 과거 재자본화 이력으로 표시합니다. 금융공시에서 발견한 과거 발행을 현재 common에 재가산하거나 기존 FD 잔액에서 차감하지 않습니다. 8-K와 반복된 거래는 합산하지 않고 근거 링크를 대조하며, 과거 이력은 현재 catalyst와 별도 섹션에 표시합니다.

SEC cover의 등록 증권 종류와 티커를 먼저 연결합니다. 같은 CIK의 보통주·상장 채권·preferred·워런트를 분리하고, ETF 및 비보통주 증권은 `EXCLUDED`로 남깁니다. 확인되지 않은 증권은 `DATA_HOLD`이며 회사 보통주 수를 임의로 적용하지 않습니다.

최근 60일의 material 8-K와 명시적으로 인용된 EX-99를 함께 읽습니다. 진행 중인 현금합병/CVR·청산을 후속 일반 계약이 가리지 않도록 보존하고, 다른 거래는 최신 공시를 우선합니다. 선택한 이벤트와 전체 검토 이력·SEC 링크는 `event_ledger.csv`에 저장합니다. 완료되어 주식이 현금으로 전환된 합병은 신규 후보에서 제외합니다.

청산배당은 선언·지급을 구분하고 record/payment/ex-dividend 날짜와 due bills, 예정 상폐·해산일을 표시합니다. 현금합병의 고정 현금과 조건부 CVR은 별도로 표시하며 예시 총액을 확정 지급액으로 취급하지 않습니다.

SPAC 정관의 미래 조건부 청산 문구는 현재 청산으로 분류하지 않습니다. 실제 승인·선언·진행 중인 청산 근거를 요구합니다. 주식교환 합병과 조건부 CVR은 `REVERSE_MERGER_CVR`로 구분하며, 예상 합병 후 지분율은 현재 FD 주식 수로 환산하지 않습니다. CVR만 확인되고 대가 구조가 불명확하면 `DATA_HOLD`입니다.

일반 보통주 주주의 대가가 확인되면 현금+주식 합병은 `MERGER_CASH_STOCK`, 주식교환 합병은 `MERGER_STOCK`으로 표시합니다. 주당 현금·교환비율·수취 증권과 현금 하향조정 조건을 보고서에 함께 표시하며, 단주 정산이나 임직원 주식보상에 대한 현금은 보통주 합병 현금대가로 취급하지 않습니다. 권리공모·채권의 주식 교환에서는 공모 주식 수·가격·조달액·예상 추가 발행·예상 부채 감소·거래 후 예상 주식 수를 구분하며, 예상 수치를 현재 FD 분모에 자동 반영하지 않습니다.

우선주·워런트의 “청산·해산 시” 지급 순위는 회사의 현재 청산 근거가 아닙니다. 승인된 청산 계획과 진행 중인 청산 활동을 구분해서 확인하며, 보통주 청산배당은 실제 지급 선언·승인과 보통주 대상 금액이 함께 확인돼야 표시합니다. 주식 액면가·우선주 지급액을 보통주 배당으로 사용하지 않습니다. 권리방어계약은 자본구조 이벤트로, 기존 증권의 재판매 등록은 신규 발행과 구분해 표시합니다.

일반 신용약정 개정의 만기·한도·가격조건 변경은 특수상황 후보에서 `REJECT`합니다. 채무의 주식 전환, 실제 채무면제·디폴트 해소, 신규 워런트 등 구조적 근거를 확인한 부채 이벤트에만 catalyst 점수를 부여합니다. 대출 한도 감소는 채무 상환으로 해석하지 않습니다. 구조적 중요성을 확인할 수 없는 부채 이벤트는 `DATA_HOLD`입니다.

주식 대가가 예정되어 있거나 현재 stock options/RSUs/PSUs의 주식 환산이 미해결이면 FD 배수는 공란입니다. 신주 대가의 달러 금액은 발행주식 수가 아닙니다. 신규 워런트는 과거 잔량과 대조해야 하므로 공시별 `max()`만으로 총량을 확정하지 않습니다. 우선주 발행·유통 0과 발행 가능 한도는 별개이고, 표의 과거 earnout 현금 지급을 다른 행의 주식 발행 문구와 합치지 않습니다.

`SAFE_TO_ACT=FALSE`는 자동 후보 선정 완료를 의미하지 않습니다. 보고서의 material special situations 섹션은 `DATA_HOLD` 상태에서도 핵심 거래를 보여주는 원문 검토 목록입니다.

## 실행

```bash
python -m pip install -e .
export SEC_USER_AGENT="Your Name your@email.com"

ssm scan --days 7 --out output
ssm check AAPL --out output
pytest -q
```

기본 시장데이터 provider는 `yfinance`입니다. Alpaca를 사용하려면:

```bash
export SSM_MARKET_PROVIDER=alpaca
export APCA_API_KEY_ID=...
export APCA_API_SECRET_KEY=...
```

## SEC discovery modes

SSM은 두 가지 SEC discovery 경로를 지원합니다.

- `SSM_SEC_DISCOVERY_MODE=atom` — GitHub-hosted/public 배포 기본값. SEC Latest Filings Atom feed로 신규 filing을 발견하고, `data.sec.gov/submissions` + `companyfacts`로 검증한 뒤 filing 본문을 직접 읽습니다.
- `SSM_SEC_DISCOVERY_MODE=daily-index` — 로컬/self-hosted 전용. EDGAR daily master index를 사용합니다.
- `auto` — daily-index를 먼저 시도하고 403이면 atom으로 자동 fallback합니다.

GitHub-hosted runner에서는 EDGAR daily-index가 403을 반환할 수 있지만, Atom feed, submissions API, companyfacts API, 개별 filing 문서는 정상 접근되는 것을 endpoint probe로 확인했습니다.

```bash
export SSM_SEC_DISCOVERY_MODE=atom
ssm scan --days 7 --out output
```

## 결과 파일

- `output/quality.json`
- `output/candidates.csv`
- `output/dilution_check.csv`
- `output/event_ledger.csv`
- `output/latest.md`

## 수동 Override

SEC filing의 warrant / convert / preferred 구조는 표준 XBRL 태그가 없는 경우가 많기 때문에 완전 자동화가 불가능합니다. 검증된 숫자는 `config/overrides.json`에 기록하고 source/as-of를 남깁니다.

미해결 희석 항목은 다른 공시나 첨부자료에 희석 언급이 없다는 이유로 해소되지 않습니다. 신뢰도가 low이면 DATA_HOLD를 유지하고 완전희석 시총·FD 배수·완전희석 총주식수는 빈칸으로 출력합니다. 추출한 개별 숫자는 검토용이며, 현재 잔량과 과거 발행·행사 수량 및 역분할 조정 여부를 대조하기 전에는 확정 cap table이 아닙니다.

로컬/스킬 사용자의 결과는 해당 실행자의 작업 환경에만 저장합니다. 저장소 운영자용 Actions 스캔 결과는 별도 7일 만료 아티팩트에 저장하며, `output/`에 게시하지 않습니다. 반드시 `run_metadata.json`의 실행 날짜·run_id를 확인하고 기존 결과를 최신으로 간주하지 마세요.

## v1 배포 범위

1. SEC recent filing scanner
2. Event proof classifier
3. Conservative dilution parser
4. Hard gate / DATA_HOLD
5. Deterministic research-priority score
6. Existing watchlist recheck

향후 우선순위:

- filing table parser 강화
- warrant strike / exercise cash 자동 추출
- S-1/S-3/424B shelf capacity ledger
- reverse split / Nasdaq deficiency history
- 13D/G / Form 4 strategic validation
- thesis diff / position tracker


## 10-Q / 10-K second pass

신규 후보 발견은 8-K / S-1 / S-3 / 424B / 13D/G / Proxy 등 이벤트성 filing에서 시작합니다.

후보가 잡히면 최신 10-Q 또는 10-K primary document를 별도로 다시 읽어 다음 항목을 2차 검증합니다.

- warrants / pre-funded warrants
- convertible notes / preferred
- ATM / equity line
- stock-based compensation / RSUs
- going concern
- related-party transactions
- subsequent events
- debt / commitments / contingencies
- stockholders' equity

이 2차 검토가 완료되지 않으면 해당 후보는 `DATA_HOLD`를 유지합니다.

이벤트 filing과 10-Q/K에 같은 증권이 반복 기재되는 경우 share equivalents는 단순 합산하지 않고 보수적으로 각 항목의 최대값을 사용해 중복계산을 피합니다.
