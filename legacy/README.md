# legacy/ — 배포되지 않는 보관용

리팩터링 전 루트에 흩어져 있던 모듈들입니다. 전부 상대 임포트(`from .base import Job`)를
쓰고 있어서 루트에 그대로 두면 `import telegram` 같은 구문이 `app/telegram.py` 대신
이 파일들을 집어갑니다. 실제로 그 사고가 나서 여기로 옮겼습니다. **지운 게 아닙니다.**

대부분은 `app/` 아래 최신본이 있는 구버전이지만, **두 개는 다릅니다.**

## 결정이 필요한 것: 잡코리아 어댑터가 두 벌입니다

| | `legacy/jobkorea.py` (178줄) | `app/sources/jobkorea.py` (158줄) |
|---|---|---|
| 방식 | 태그 후보 목록 + `JOBKOREA_FIELD_MAP` 오버라이드 | 공개 샘플 기준 고정 매핑 + `AREA_CODES` |
| 지역 | 텍스트 태그 후보에서 탐색 | `AreaCode` 코드표 변환 |
| 부속 도구 | `legacy/probe.py` (구조 탐색기) | 없음 |
| README 문서화 | **이쪽** (`probe` 명령, `JOBKOREA_FIELD_MAP` 설명) | 일부 |

README 는 `legacy` 쪽을 설명하는데 실제로 로드되는 건 `app/sources/` 쪽입니다.
그리고 `python -m app.main probe jobkorea` 는 `app/probe.py` 가 없어서 지금 동작하지
않습니다.

잡코리아는 아직 승인도 안 났으니 급한 문제는 아니지만, 승인되면 둘 중 하나를 골라
`app/` 으로 확정해야 합니다. 스키마를 모르는 상태에서는 필드맵+probe 쪽이
유리합니다 — 실제 응답을 보고 맞추는 도구가 딸려 있으니까요.
