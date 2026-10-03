# 희석 목적·재자본화 문맥 구현 기준

사용자의 2026-10-03 지시를 기존 SEC 이벤트·FD 검증 흐름에 적용한다. 티커 예외, 호재 점수, PASS 승격은 추가하지 않는다.

## 인터페이스

- `ssm/recapitalization.py`: `capital_context(text)`는 원문에서 발행 여력, 완료/예정 발행, 자금 목적, 완료/예정 청구권 제거와 근거를 추출한다. `reconcile_capital_context(dilution, context, financial_text, event_date, baseline_date)`는 명시적인 거래 전·후 주식 수와 동일 instrument 대조가 가능한 경우에만 FD 항목을 조정한다.
- `event_terms.capital_context`: 기존 거래조건과 함께 보존한다. 미확정 금액·주식 수·상환은 null 또는 PLANNED로 남긴다. 다른 공시의 자금과 상환을 이름·시점 확인 없이 연결하지 않는다.
- 리포트는 actual / planned, 발행 증가율 `new/pre`, 지분 감소율 `new/(pre+new)`, 원문 통화의 청구권 감소, 문맥 판정과 미확정을 함께 표시한다.
- 동일 transaction의 반복 공시는 합산하지 않는다. 금액 합계를 신주 수 또는 전환 주식 수로 대체하지 않는다.

## 계산·보호 기준

Authorized 증가만으로 common·FD는 늘리지 않는다. 실제 common 발행은 명시적인 거래 전·후 common 수와 현재 기준 수를 대조하며, 이미 post 수이면 재가산하지 않는다. 과거 금융공시에 있는 instrument는 같은 이름·수량과 전량 소멸 증거가 맞을 때만 제거한다. 부분 상환, 다른 시리즈, 재차 발행, 단위/날짜 불명확은 FD를 미확정으로 유지한다.

자금 목적은 DEBT_REPAYMENT / PREFERRED_REDEMPTION / ACQUISITION / WORKING_CAPITAL / GENERAL_CORPORATE / UNKNOWN이다. 문맥은 ISSUANCE_CAPACITY / DILUTION_ONLY / RECAPITALIZATION_BALANCE_SHEET_IMPROVEMENT / RECAPITALIZATION_MIXED / UNKNOWN_USE_OF_PROCEEDS로 표시하되 투자추천으로 해석하지 않는다. 예정 상환은 이미 제거된 청구권으로 합산하지 않는다. 금리·배당 감소는 실제 원문 수치만 표시하며 가정으로 만들지 않는다.

## 검증 순서

1. authorized와 actual 분리, 계획/완료 및 다른 주체·instrument 혼동 방지 테스트를 먼저 실패시킨다.
2. 공통 문맥 추출과 두 희석률을 구현한다.
3. 거래 전/후 common 대조, 동일 instrument 제거, 부분/불확실 소멸의 DATA_HOLD를 검증한다.
4. 기존 이벤트·pipeline·리포트에 연결하고 전체 테스트를 실행한다.
5. NNBR의 SEC 9/30 authorized 90M→180M을 회귀사례로 검증한다. 10/2 회사 발표의 10/5 예정 PIPE를 완료로 만들지 않는다. 운영·공개판에 같은 엔진을 반영하고 CI를 확인한다.

## 적용 범위

이 레이어는 기존 material 8-K 검토 대상의 본문과 인용된 EX-99에서 명시적인 문장을 추출한다. 모든 ATM/워런트 행사, 표, EX-4/EX-10의 자금 목적을 완전히 해석하는 기능은 아니다. 기존 희석·exhibit 검증은 유지하며, 근거가 부족한 자금 목적·주식 수·거래 후 FD는 확정하지 않는다. 자본 행위에 직접 연결된 날짜가 없거나 서로 다르면 발행/소멸을 금융공시 잔액에 자동 반영하지 않는다.

완료 문맥의 이름은 청구권 감소 사실을 설명하며 기업가치 증가나 주가 상승 판단이 아니다. 검증은 NNBR SEC 9/30 본문의 capacity 추출과 계획/완료·금액/주체 연결·동일 instrument 회귀 사례에 한정한다. 배포와 전체 유니버스 재스캔은 별도이며, 기존 스캔 파일은 새 엔진의 재검증 결과로 재표시하지 않는다.
