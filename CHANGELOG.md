# Changelog

## 1.1.4 — 2026-10-03

- 터미널에서 `scan` / `check` 실행 중 새 버전을 감지하면 실제 TTY에서 `Update now? [y/N]` 확인을 표시. 기본값은 거절이며 비대화형 CI/파이프/에이전트 실행은 입력 대기 없이 기존 안내만 출력.
- 사용자가 업데이트를 승인하면 immutable `release.json` 검증 경로로 업데이트한 뒤 원래 `scan` / `check` 명령을 새 프로세스로 다시 실행해 최신 코드로 작업을 계속함.
- 업데이트 실패 시 실패 원인과 계속 사용하는 현재 SSM 버전을 명시하고 기존 버전으로 진행.
- 일반 콘솔 진입점은 `python -m ssm.cli`로 재실행해 Windows의 `ssm.exe` 같은 launcher도 안전하게 처리하고, 스킬 번들의 `scripts/run_ssm.py`는 원래 bundle entrypoint를 유지.
- ChatGPT/Codex 스킬은 scan/check 전에 버전을 확인하고 새 버전이 있으면 자연어로 업데이트 여부를 질문. `ㅇㅇ`, `ㄱㄱ`, `해줘`, `go ahead`처럼 명확한 승인 표현을 허용하며 `y/n` 형식을 강제하지 않음.

## 1.1.3 — 2026-10-03

- `release.json`을 수동 관리하지 않고 release/build 과정에서 `pyproject.toml` 버전, release tag, source commit, managed-file SHA-256을 이용해 자동 생성.
- updater가 moving `main/pyproject.toml`과 `main.zip`을 각각 읽는 방식을 제거하고, 최신 GitHub Release의 `release.json`을 먼저 검증한 뒤 manifest가 지정한 immutable `source_commit` archive만 사용.
- archive 적용 전에 project version, source commit, managed-file hash를 검증하고 하나라도 맞지 않으면 설치 파일을 변경하지 않음.
- bundle 업데이트는 검증된 managed files만 적용하며 기존 watchlist/overrides/output/`SEC_USER_AGENT` 보존 및 copy 실패 rollback 정책 유지.
- Git checkout은 unpinned `git pull` 대신 clean working tree에서 manifest commit을 fetch 후 fast-forward-only 적용. pip 설치도 commit-pinned archive URL만 사용.
- manifest version mismatch, archive/source_commit mismatch, old→new update, mutation rollback, user-file preservation 회귀테스트 및 현재 checkout의 manifest/project version CI 불변식 추가.
- `v*` tag release workflow가 전체 테스트 후 `release.json`을 자동 생성·검증하고 GitHub Release asset으로 게시.
- v1.1.2 사용자는 이번 한 번 기존 updater로 v1.1.3에 올라온 뒤, 이후 버전부터 immutable release manifest 경로를 사용.

## 1.1.2 — 2026-10-03

- `ssm version`으로 현재 설치 버전과 최신 공개 버전을 확인할 수 있게 함.
- `ssm update`와 `ssm update --dry-run` 추가.
- `scan` / `check` 실행 시 새 버전이 있으면 업데이트 안내만 표시하고 강제 업데이트는 하지 않음.
- 업데이트 시 `config/watchlist.csv`, `config/overrides.json`, `output/`, `SEC_USER_AGENT` 보존.
- 번들 파일 교체 중 실패하면 덮어쓴 파일을 기존 상태로 롤백.
- Git checkout은 fast-forward-only pull, 일반 pip 설치본은 공개 GitHub archive에서 업데이트.
- v1.1.1 이하 설치본은 updater가 없으므로 v1.1.2로 올라올 때 한 번만 재설치 필요.

## 1.1.1 — 2026-10-03

- 최신 10-Q/10-K의 자본구조·subsequent events 및 관련 자금사용 문맥에 read-only 재자본화 보완 검증 추가.
- 거래 날짜·named financing·instrument identity·금액·전량/부분 상환 결과를 대조. 근거 없는 자금 연결이나 공시 간 충돌은 UNKNOWN/DATA_HOLD 유지.
- 금융공시의 과거 주식 발행과 상환은 현재 common/FD에 재가산·차감하지 않음. 8-K 반복 공시는 수량 합산 없이 근거 링크로 보존.
- authorized capacity는 대표 이벤트에 유지하고, 과거 희석·재자본화는 별도 Financial capital history 섹션에 표시.
- NNBR 실제 최신 10-Q와 9/30 8-K 원문 대조, 일반 자금 출처·금액·증권·날짜 연결 회귀 검증 추가. 전체 유니버스 재스캔은 포함하지 않음.

## 1.1.0 — 2026-10-03

- 희석 목적·재자본화 문맥 추가: 신규 주식, 자금 목적, 실제/예정 부채·우선주 청구권 감소를 함께 표시.
- Authorized capacity와 실제 발행, 발행 증가율과 기존 주주의 지분 감소율을 분리. common/pre-funded warrant 대체 총량은 확정 보통주 수로 사용하지 않음.
- 같은 instrument·전량 소멸·기준 수·거래 시점이 모두 확인된 경우만 기존 전환/우선주 FD 항목 제거. 부분 상환, 재발행 및 날짜 불명확은 DATA_HOLD 유지.
- 과거 공시의 자본 변동도 대표 이벤트와 함께 이력·근거 링크로 표시. 문맥이 좋아도 희석 경고나 PASS 게이트를 완화하지 않음.
- NNBR authorized/예정 PIPE 및 일반적인 완료·부분 상환·통화·중복·주체/금액 연결 회귀 검증 추가. 전체 유니버스 재스캔 및 무오류 보장을 뜻하지 않음.

## 1.0.1 — 2026-10-02

- 인수 대가의 원문 통화를 보존하고, 회사가 공시한 USD 환산액과 조건부 earnout을 별도 표시.
- 실제 합병 완료를 알리는 7.01 공시를 경제 이벤트 검토에 포함. 완료 증거와 Form 25의 보통주 교환 등록 제거를 함께 확인해 기존 증권을 제외.
- 티커별 override 없이 공통 규칙과 통화·lifecycle 회귀 검증 추가.

## 1.0.0 — 2026-10-02

- 공개 저장소용 GPT 스킬 설치·최초 환경 설정·실제 엔진 실행 지침 추가.
- 설치 폴더와 작업 폴더가 달라도 기본 설정을 찾는 `scripts/run_ssm.py` 추가.

- 최신 SEC 이벤트·10-Q/K 2차 검증·증권 종류 판별 및 희석 보호 규칙을 배포판에 반영.
- Introductory Note의 실제 closing과 자본변동을 보존하고, 비material 공시가 완료 거래를 가리는 선택 오류 교정.
- 동일 법인 또는 원문에서 정의된 별칭으로 확인한 기존 계약의 현금·주식 대가를 최신 규제 업데이트에 연결.
- 거래 후 주식 수·역분할·티커 전환이 미조정이면 시가총액·FD 계산을 미확정으로 표시하고 DATA_HOLD 유지.
- 티커별 예외 없이 실전 영향이 있는 오류만 공통 원인 단위로 수정하는 v1 정책 반영.
- 개인 워치리스트·override·인증정보·내부 output 제외.
- Python CLI, 테스트, 에이전트 지침, 빈 설정 및 설치 안내 포함.
