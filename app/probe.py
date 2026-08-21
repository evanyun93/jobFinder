"""소스 진단 도구.

    python -m app.main probe worknet

"키는 승인됐는데 왜 안 되지"를 추측이 아니라 증거로 판정하기 위한 것.
같은 인증키로 파라미터만 바꿔가며 찔러보고 응답 코드가 어떻게 갈리는지
보여준다. 코드가 갈리는 지점이 곧 원인이다.
"""
from __future__ import annotations

import re

import httpx

from .config import cfg

WORKNET_EP = "http://openapi.work.go.kr/opi/opi/opia/wantedApi.do"

_CODE = re.compile(r"<messageCd>([^<]*)</messageCd>")
_MSG = re.compile(r"<(?:errMsg|message)>([^<]*)</")
_TOTAL = re.compile(r"<total>([^<]*)</total>")


def _call(params: dict, timeout: float = 20.0):
    try:
        r = httpx.get(WORKNET_EP, params=params, timeout=timeout)
    except Exception as e:
        return None, "요청 실패: %s" % type(e).__name__, None
    body = r.text.strip()
    code = _CODE.search(body)
    msg = _MSG.search(body)
    total = _TOTAL.search(body)
    return (code.group(1) if code else None,
            msg.group(1) if msg else "",
            total.group(1) if total else None)


def probe_worknet() -> int:
    key = cfg.worknet_key
    if not key:
        print("WORKNET_AUTH_KEY 가 .env 에 없습니다.")
        return 1

    print("=== 1. 키 형식 ===")
    problems = []
    if len(key) != 36:
        problems.append("길이가 %d자입니다 (UUID 는 36자)" % len(key))
    if key.count("-") != 4:
        problems.append("하이픈이 %d개입니다 (UUID 는 4개)" % key.count("-"))
    if any(ch in key for ch in ' "\'\n\t'):
        problems.append("공백이나 따옴표가 섞여 있습니다")
    print("  %s...%s  (%d자)" % (key[:8], key[-4:], len(key)))
    for p in problems:
        print("  !! " + p)
    if not problems:
        print("  형식 정상 (UUID)")

    print("\n=== 2. 응답 코드 비교 ===")
    print("  파라미터를 바꿔가며 같은 키로 호출합니다.")
    print("  이 API 는 '파라미터 검사 -> 인증키 검사' 순서라,")
    print("  002 가 나온다는 건 파라미터는 통과하고 키에서 막혔다는 뜻입니다.\n")

    base = {"authKey": key, "returnType": "XML"}
    cases = [
        ("목록 (앱이 실제로 쓰는 호출)",
         dict(base, callTp="L", startPage=1, display=10)),
        ("callTp 를 일부러 틀리게",
         dict(base, callTp="ZZZ", startPage=1, display=10)),
        ("상세, 필수항목 없이",
         dict(base, callTp="D")),
    ]
    codes = {}
    for name, params in cases:
        code, msg, total = _call(params)
        codes[name] = code
        print("  %-28s code=%-5s %s%s" % (
            name, code or "-", msg[:34],
            "  total=" + total if total else ""))

    print("\n=== 3. 판정 ===")
    listed = codes.get("목록 (앱이 실제로 쓰는 호출)")
    if listed is None:
        print("  응답을 파싱하지 못했습니다. 네트워크나 엔드포인트를 확인하세요.")
        return 1
    if listed == "002":
        print("  인증키가 거부되고 있습니다 (002).")
        print("  파라미터를 틀리게 하면 008 이 나오므로, 파라미터는 정상이고")
        print("  키 검사에서 막히는 게 확실합니다.")
        print()
        print("  포털에서 확인할 것:")
        print("   - '처리상태'가 승인이어도 서비스별로 따로 승인됩니다.")
        print("     '채용정보' 항목이 승인인지 확인하세요.")
        print("   - 승인 직후면 반영까지 시간이 걸릴 수 있습니다 (하루 이상 걸리기도 함).")
        print("   - 호출 IP 를 등록하는 항목이 있으면 현재 IP 가 맞는지 확인하세요.")
        print("     서버리스는 IP 가 매번 바뀌므로 IP 제한이 있으면 쓸 수 없습니다.")
        print("   - 공공데이터포털(data.go.kr) 의 serviceKey 와 혼동하지 마세요.")
        print("     이 어댑터는 openapi.work.go.kr 이 발급한 UUID 를 씁니다.")
        print()
        print("  위를 다 확인해도 002 면 한국고용정보원에 문의하세요.")
        print("  문의할 때 이 출력을 그대로 붙이면 설명이 빨라집니다.")
        return 1
    if listed is None or listed == "":
        print("  정상 응답입니다. 워크넷이 살아났습니다.")
        return 0
    print("  예상 못한 코드입니다: %s" % listed)
    return 1


def main(name: str) -> int:
    if name == "worknet":
        return probe_worknet()
    print("지원하는 소스: worknet")
    print("(잡코리아용 probe 는 legacy/probe.py 에 있습니다 - legacy/README.md 참고)")
    return 1
