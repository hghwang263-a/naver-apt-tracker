# 인덕원 아파트 매물 동향 Tracker

네이버 부동산의 4개 단지 매매 매물을 주기적으로 수집하고, GitHub Pages에서 매물 수/최저호가/가격변경/신규·삭제 매물을 확인하기 위한 개인 분석용 프로젝트입니다.

## 추적 단지

| 단지 | complexNo |
|---|---:|
| 인덕원대림2차 | 8194 |
| 래미안인덕원더포인트 | 8193 |
| 두산위브센트럴2단지 | 26414 |
| 두산위브센트럴1단지 | 24900 |

> 네이버 내부 API는 공식 공개 API가 아닙니다. 구조가 변경되면 `crawler.py` 수정이 필요할 수 있습니다.

## GitHub에 올리는 방법

1. GitHub 로그인
2. `New repository` → Repository name을 `naver-apt-tracker`로 입력
3. Public repository를 선택
4. 이 ZIP의 압축을 풀고 **파일/폴더 전체를 repository에 업로드**
5. GitHub에서 `Settings → Actions → General`로 이동
6. Workflow permissions에서 **Read and write permissions**를 선택하고 저장
7. `Actions` 탭 → `Naver Apt Crawler` → `Run workflow`로 수동 실행하여 테스트
8. `Settings → Pages`
9. Source를 `Deploy from a branch`
10. Branch를 `main`, Folder를 `/docs`로 선택 후 Save

몇 분 뒤:
`https://YOUR_GITHUB_ID.github.io/naver-apt-tracker/`

형태로 대시보드가 열립니다.

## 자동 수집

기본 설정은 매일 한국시간 오전 8:10 / 오후 6:10입니다.

`.github/workflows/crawl.yml`의 cron은 UTC 기준입니다.

- 23:10 UTC = 08:10 KST
- 09:10 UTC = 18:10 KST

GitHub Actions의 스케줄 실행은 약간 지연될 수 있습니다.

## 로컬에서 실행

Python 3.11+ 권장.

```bash
pip install -r requirements.txt
playwright install chromium
python crawler.py
```

수집 결과:
- `docs/data.json`

## 대시보드가 보여주는 것

- 현재 매매 매물 수
- 최저 호가
- 10.3억 이하 매물 수
- 전일 대비 매물 수 변화
- 최근 가격 인하/인상
- 신규 매물
- 사라진 매물
- 최근 스냅샷
- 매물별 최초 관측일/마지막 관측일

## 주의

이 프로젝트는 개인적인 시장 분석을 위한 것입니다. 네이버의 이용약관, robots 정책, 데이터 이용 제한 등을 준수하고 요청 빈도를 과도하게 높이지 마세요. 수집 데이터에는 중개사 연락처 등 불필요한 개인정보를 저장하지 않습니다.


## iPhone 업로드 방식

루트 파일은 GitHub의 `Add file → Upload files`로 업로드합니다.

`.github/workflows/crawl.yml`은 GitHub 웹에서:
`Add file → Create new file`
로 만든 뒤 파일명에 `.github/workflows/crawl.yml`을 입력해 생성할 수 있습니다.

Pages는:
`Settings → Pages → Deploy from a branch → main → /(root)`
로 설정합니다.
