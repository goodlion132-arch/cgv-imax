from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from playwright.async_api import async_playwright

BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/cinema"
API_URL = "https://api.cgv.co.kr/cnm/atkt/searchMovScnInfo"

CONFIG_PATH = Path("config.json")
STATE_PATH = Path("state.json")

KST = timezone(timedelta(hours=9))


class WatchError(Exception):
    pass


class AccessLimited(WatchError):
    pass


@dataclass(frozen=True)
class Showtime:
    date: str
    movie: str
    screen: str
    start: str
    end: str
    free: int
    total: int
    screen_no: str
    sequence: str
    movie_no: str

    @property
    def key(self) -> str:
        return "|".join([
            self.date,
            self.movie_no,
            self.screen_no,
            self.sequence,
            self.start,
            self.screen,
        ])

    @property
    def date_label(self) -> str:
        d = self.date
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d

    @property
    def time_label(self) -> str:
        s = "".join(ch for ch in self.start if ch.isdigit())
        return f"{s[-4:-2]}:{s[-2:]}" if len(s) >= 4 else (self.start or "시간 미상")


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def contains_any(text: str, words: list[str]) -> bool:
    t = text.casefold()
    return any(w.casefold() in t for w in words)


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_payload(payload: Any, fallback_date: str) -> list[Showtime]:
    if not isinstance(payload, dict):
        raise WatchError("CGV 응답 형식이 예상과 다릅니다.")

    status_code = payload.get("statusCode")
    if status_code not in (None, 0, "0"):
        raise WatchError(str(payload.get("statusMessage") or f"CGV statusCode={status_code}"))

    rows = payload.get("data") or []
    if not isinstance(rows, list):
        return []

    result: list[Showtime] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        result.append(
            Showtime(
                date=str(r.get("scnYmd") or fallback_date),
                movie=str(r.get("movNm") or ""),
                screen=str(r.get("scnsNm") or r.get("scnNm") or ""),
                start=str(r.get("scnsrtTm") or r.get("scnSrtTm") or ""),
                end=str(r.get("scnendTm") or ""),
                free=to_int(r.get("frSeatCnt")),
                total=to_int(r.get("stcnt") or r.get("seatCnt")),
                screen_no=str(r.get("scnsNo") or ""),
                sequence=str(r.get("scnSseq") or ""),
                movie_no=str(r.get("movNo") or r.get("prodNo") or ""),
            )
        )
    return result


def ntfy_send(title: str, message: str, priority: str = "high") -> None:
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        raise WatchError("GitHub Secret NTFY_TOPIC이 설정되지 않았습니다.")

    req = Request(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": "movie_camera,rotating_light",
            "Click": BOOKING_URL,
        },
    )
    with urlopen(req, timeout=20) as response:
        if response.status >= 300:
            raise WatchError(f"ntfy HTTP {response.status}")


def alert_message(theater: str, sessions: list[Showtime]) -> str:
    lines = [f"{theater}에서 새 IMAX 회차가 확인됐습니다."]
    for s in sorted(sessions, key=lambda x: (x.date, x.start)):
        seat = f" · 잔여 {s.free}/{s.total}" if s.total else ""
        lines.append(
            f"\n🎬 {s.movie}\n"
            f"📅 {s.date_label} {s.time_label}\n"
            f"🎥 {s.screen}{seat}"
        )
    lines.append("\n알림을 눌러 CGV 예매 페이지를 여세요.")
    return "\n".join(lines)


def should_send_error_notice(state: dict[str, Any]) -> bool:
    raw = state.get("last_error_notice")
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(raw)
        return datetime.now(KST) - previous >= timedelta(hours=12)
    except Exception:
        return True


async def main() -> None:
    config = load_json(CONFIG_PATH, {})
    if not config:
        raise SystemExit("config.json을 읽을 수 없습니다.")

    state = load_json(
        STATE_PATH,
        {
            "dates": {},
            "first_success": False,
            "last_error_notice": None,
        },
    )

    theater = config["theater"]
    site_no = str(theater["site_no"])
    theater_name = str(theater["name"])
    movie_keywords = list(config["movie_keywords"])
    screen_keywords = list(config["screen_keywords"])

    watch = config["watch"]
    full_days = int(watch.get("full_scan_days", 30))
    fast_start = int(watch.get("fast_window_start_days", 17))
    fast_end = int(watch.get("fast_window_end_days", 24))
    request_gap = float(watch.get("request_gap_seconds", 1.2))

    now = datetime.now(KST)
    today = now.date()

    # 첫 정상 실행은 전체 범위를 기준값으로 잡는다.
    # 이후 매시 첫 실행 무렵에는 전체 범위를 확인하고,
    # 나머지 5분 실행에서는 3주 전후를 집중 확인한다.
    first_run = not bool(state.get("first_success"))
    hourly_full_scan = now.minute < 10
    if first_run or hourly_full_scan:
        offsets = list(range(0, full_days + 1))
        scan_type = "FULL"
    else:
        offsets = list(range(fast_start, fast_end + 1))
        scan_type = "FAST"

    dates = [(today + timedelta(days=i)).strftime("%Y%m%d") for i in offsets]

    print(f"[{now:%Y-%m-%d %H:%M:%S KST}] {scan_type} scan")
    print(f"극장={theater_name} / siteNo={site_no} / 날짜={len(dates)}개")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            page = await context.new_page()

            response = await page.goto(
                BOOKING_URL,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            if response and response.status in (401, 403, 429):
                raise AccessLimited(f"CGV 예매 페이지 HTTP {response.status}")
            if response and response.status >= 400:
                raise WatchError(f"CGV 예매 페이지 HTTP {response.status}")

            await page.wait_for_timeout(2500)

            all_new: list[Showtime] = []
            changed = False

            for ymd in dates:
                query = urlencode({
                    "coCd": "A420",
                    "siteNo": site_no,
                    "scnYmd": ymd,
                    "rtctlScopCd": "08",
                })
                url = f"{API_URL}?{query}"

                result = await page.evaluate(
                    """
                    async (url) => {
                      try {
                        const r = await fetch(url, {
                          method: "GET",
                          credentials: "include",
                          headers: {
                            "Accept": "application/json, text/plain, */*"
                          }
                        });
                        return {status: r.status, text: await r.text()};
                      } catch (e) {
                        return {status: 0, text: String(e)};
                      }
                    }
                    """,
                    url,
                )

                status = int(result.get("status") or 0)
                text = str(result.get("text") or "")

                if status in (401, 403, 429):
                    raise AccessLimited(f"CGV 시간표 API HTTP {status}")
                if status != 200:
                    raise WatchError(f"{ymd} 시간표 API HTTP {status}: {text[:120]}")

                try:
                    payload = json.loads(text)
                except Exception as e:
                    raise WatchError(f"{ymd} JSON 파싱 실패: {e}") from e

                rows = parse_payload(payload, ymd)
                matches = [
                    s for s in rows
                    if contains_any(s.movie, movie_keywords)
                    and contains_any(s.screen, screen_keywords)
                ]

                date_state = state.setdefault("dates", {}).get(ymd, {})
                initialized = bool(date_state.get("initialized"))
                previous = set(date_state.get("keys") or [])
                current = {s.key for s in matches}

                # 첫 관측은 baseline. 다음 관측부터 새로 생긴 회차만 알림.
                if initialized:
                    new_keys = current - previous
                    if new_keys:
                        all_new.extend(s for s in matches if s.key in new_keys)

                new_date_state = {
                    "initialized": True,
                    "keys": sorted(current),
                }
                if date_state != new_date_state:
                    changed = True
                state["dates"][ymd] = new_date_state

                print(f"  {ymd}: 대상 {len(matches)}회")
                await page.wait_for_timeout(int(request_gap * 1000))

            await browser.close()

        # 과거 날짜 상태 제거
        valid_cutoff = today.strftime("%Y%m%d")
        old_dates = [d for d in state.get("dates", {}) if d < valid_cutoff]
        for d in old_dates:
            state["dates"].pop(d, None)
            changed = True

        if all_new:
            ntfy_send(
                "🚨 CGV 인천 IMAX 오픈!",
                alert_message(theater_name, all_new),
                "urgent",
            )
            print(f"새 회차 {len(all_new)}개 → ntfy 전송")

        if not state.get("first_success"):
            state["first_success"] = True
            changed = True
            ntfy_send(
                "✅ CGV 클라우드 감시 시작",
                f"{theater_name} / 오디세이 / IMAX 감시가 정상적으로 시작됐습니다.\n"
                "PC를 꺼도 GitHub Actions가 계속 확인합니다.",
                "default",
            )

        # 정상화됐으면 오류 알림 타이머 초기화
        if state.get("last_error_notice") is not None:
            state["last_error_notice"] = None
            changed = True

        if changed:
            save_json(STATE_PATH, state)

    except Exception as e:
        print(f"ERROR: {e}")

        # 같은 오류로 5분마다 푸시 폭탄이 오지 않도록 12시간에 한 번만 오류 알림.
        if should_send_error_notice(state):
            try:
                ntfy_send(
                    "⚠️ CGV 클라우드 감시 오류",
                    "GitHub 서버에서 CGV 시간표를 확인하지 못했습니다.\n"
                    f"원인: {type(e).__name__}: {str(e)[:250]}\n\n"
                    "CGV가 클라우드 접속을 제한한 경우 이 프로그램은 제한을 우회하지 않습니다.",
                    "high",
                )
                state["last_error_notice"] = datetime.now(KST).isoformat()
                save_json(STATE_PATH, state)
            except Exception as notify_error:
                print(f"오류 알림 전송도 실패: {notify_error}")

        # Actions에서 실패 표시가 나도록 종료 코드 1
        raise


if __name__ == "__main__":
    asyncio.run(main())
