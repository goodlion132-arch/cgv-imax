# CGV 인천 IMAX — 무료 클라우드 감시

PC를 켜두지 않아도 **GitHub Actions**가 주기적으로 CGV 인천의
`오디세이 + IMAX` 회차를 확인하고 **ntfy**로 iPhone 푸시를 보냅니다.

## 비용

이 프로젝트를 **Public repository(공개 저장소)** 로 사용하면
표준 GitHub-hosted Actions 실행은 무료입니다.

> `NTFY_TOPIC`은 코드에 적지 않고 GitHub Actions Secret으로 넣습니다.

## 감시 주기

GitHub Actions 예약 실행의 최소 간격인 약 **5분**으로 설정되어 있습니다.

CGV에 불필요하게 많은 요청을 보내지 않기 위해:

- 처음 실행: 오늘 ~ 30일 뒤 전체 확인
- 매시간: 오늘 ~ 30일 뒤 전체 확인
- 나머지 5분 실행: **17~24일 뒤(약 3주 뒤)** 집중 확인

즉, 네가 발견했던 "3주 뒤 일정" 구간은 약 5분마다 확인하고,
그 밖의 날짜도 약 1시간마다 확인합니다.

GitHub의 예약 작업은 서버 사정에 따라 몇 분 늦게 실행될 수 있습니다.

---

# 설치 방법

## 1. GitHub에서 새 저장소 만들기

GitHub → `New repository`

추천 이름:
`cgv-incheon-imax-watch`

반드시:
**Public** 선택

README / .gitignore / license는 만들지 않아도 됩니다.

## 2. 이 폴더 내용을 GitHub에 업로드

이 ZIP 압축을 푼 뒤 **안쪽 파일 전체**를 저장소에 업로드합니다.

`.github/workflows/watch.yml` 경로가 그대로 올라가야 합니다.

구조:

```text
.github/
  workflows/
    watch.yml
cloud_watch.py
config.json
requirements.txt
state.json
README.md
```

## 3. ntfy 주제 만들기

iPhone의 ntfy 앱에서 `+` → Topic 구독.

다른 사람이 맞히기 어려운 긴 이름을 사용하세요.

예:
`cgv-incheon-내가정한긴랜덤문자열`

무료 공개 ntfy 서버에서는 Topic 이름을 비밀번호처럼 취급해야 합니다.
다른 사람에게 공개하지 마세요.

## 4. GitHub Secret에 넣기

저장소에서:

`Settings`
→ `Secrets and variables`
→ `Actions`
→ `New repository secret`

Name:
```text
NTFY_TOPIC
```

Secret:
```text
iPhone ntfy에서 구독한 Topic 이름
```

저장합니다.

## 5. 최초 테스트

저장소 상단 `Actions`
→ `CGV 인천 IMAX 감시`
→ `Run workflow`
→ `Run workflow`

첫 실행이 정상 완료되면 iPhone에:

`✅ CGV 클라우드 감시 시작`

알림이 옵니다.

그 뒤에는 PC를 꺼도 됩니다.

---

# 새 IMAX 회차가 열리면

기존에 없던 `오디세이 + IMAX` 회차가 새로 확인되면:

`🚨 CGV 인천 IMAX 오픈!`

푸시가 옵니다.

알림을 누르면 CGV 예매 페이지가 열립니다.

회차가 사라진 뒤 다시 나타나는 경우에도 새 회차로 다시 감지됩니다.

---

# 중요: CGV의 접속 제한

이 프로그램은 CGV가 공개한 예매 페이지를 일반 Chromium 브라우저로 확인합니다.

CGV가 GitHub 클라우드 서버 접속에 401 / 403 / 429 등 제한을 걸 경우
**그 제한을 우회하지 않습니다.**

그 경우 iPhone에:

`⚠️ CGV 클라우드 감시 오류`

알림이 오며 GitHub Actions에도 실패 기록이 남습니다.

오류 알림은 같은 문제로 5분마다 울리지 않도록 최대 약 12시간에 한 번만 보냅니다.

---

# 설정 변경

`config.json`

```json
{
  "theater": {
    "name": "CGV 인천",
    "site_no": "0002"
  },
  "movie_keywords": [
    "오디세이",
    "The Odyssey",
    "ODYSSEY"
  ],
  "screen_keywords": [
    "IMAX",
    "아이맥스"
  ]
}
```

영화가 바뀌면 `movie_keywords`만 바꾸면 됩니다.

---

# 멈추기

GitHub 저장소:
`Actions`
→ `CGV 인천 IMAX 감시`
→ 우측 `...`
→ `Disable workflow`

이렇게 하면 더 이상 자동 확인하지 않습니다.
