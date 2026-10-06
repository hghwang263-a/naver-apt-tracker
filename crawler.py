import asyncio
import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

from config import COMPLEXES, TARGET_PRICE_EOK, MAX_SNAPSHOTS

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data.json"

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


def parse_price_to_eok(price_text):
    """
    네이버 가격 문자열 예:
      '10억 3,000'
      '10억'
      '9억 8,000'
    -> 10.3 / 10.0 / 9.8
    """
    if not price_text:
        return None

    s = str(price_text).replace(",", "").strip()

    try:
        if "억" in s:
            major = float(s.split("억")[0].strip() or 0)
            rest = s.split("억", 1)[1].strip()
            minor = 0.0
            if rest:
                m = re.search(r"(\d+(?:\.\d+)?)", rest)
                if m:
                    minor = float(m.group(1)) / 10000.0
            return round(major + minor, 4)

        # 혹시 숫자로 내려오는 경우
        return round(float(re.sub(r"[^0-9.]", "", s)) / 100000000, 4)
    except Exception:
        return None


def load_data():
    if not DATA_PATH.exists():
        return {"updated_at": None, "snapshots": []}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"updated_at": None, "snapshots": []}


def save_data(data):
    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def fetch_articles(page, complex_no):
    """
    브라우저 세션을 확보한 뒤 동일 origin에서 내부 API를 호출한다.
    """
    url = f"https://new.land.naver.com/api/articles/complex/{complex_no}"

    base_params = {
        "realEstateType": "APT:ABYG:JGC",
        "tradeType": "A1",
        "priceType": "RETAIL",
        "priceMin": 0,
        "priceMax": 90000000000,
        "areaMin": 0,
        "areaMax": 900000000,
        "showArticle": "false",
        "sameAddressGroup": "false",
        "type": "list",
        "order": "rank",
    }

    all_articles = []

    for page_no in range(1, 30):
        params = dict(base_params)
        params["page"] = page_no

        result = await page.evaluate(
            """async ({url, params}) => {
                const qs = new URLSearchParams(params).toString();
                const r = await fetch(url + "?" + qs, {
                    credentials: "include",
                    headers: {"Accept": "application/json, text/plain, */*"}
                });
                return {
                    status: r.status,
                    text: await r.text()
                };
            }""",
            {"url": url, "params": params},
        )

        if result["status"] != 200:
            raise RuntimeError(
                f"API status={result['status']} complex={complex_no} page={page_no}"
            )

        payload = json.loads(result["text"])
        articles = payload.get("articleList") or []

        if not articles:
            break

        all_articles.extend(articles)

        if not payload.get("isMoreData", False):
            break

        await page.wait_for_timeout(1200)

    return all_articles


def normalize(article, complex_name, collected_at):
    price_text = (
        article.get("dealOrWarrantPrc")
        or article.get("price")
        or ""
    )

    article_no = str(
        article.get("articleNo")
        or article.get("articleConfirmNo")
        or ""
    )

    # 개인정보/중개사 연락처 등은 저장하지 않는다.
    return {
        "article_no": article_no,
        "complex_name": complex_name,
        "price_text": price_text,
        "price_eok": parse_price_to_eok(price_text),
        "area_supply": article.get("area1"),
        "area_exclusive": article.get("area2"),
        "floor": article.get("floorInfo"),
        "direction": article.get("direction"),
        "feature": article.get("articleFeatureDesc"),
        "confirm_date": article.get("articleConfirmYmd"),
        "tags": article.get("tagList") or [],
        "collected_at": collected_at,
    }


def make_snapshot(complex_name, articles, collected_at):
    listings = [
        normalize(a, complex_name, collected_at)
        for a in articles
    ]
    # article_no가 없는 비정상 응답은 제외
    listings = [x for x in listings if x["article_no"]]
    return {
        "complex_name": complex_name,
        "collected_at": collected_at,
        "listing_count": len(listings),
        "listings": listings,
    }


def calculate_changes(old_snapshot, new_snapshot):
    old = {
        x["article_no"]: x
        for x in (old_snapshot or {}).get("listings", [])
    }
    new = {
        x["article_no"]: x
        for x in new_snapshot.get("listings", [])
    }

    added = [new[k] for k in new.keys() - old.keys()]
    removed = [old[k] for k in old.keys() - new.keys()]

    price_changes = []
    for k in new.keys() & old.keys():
        op = old[k].get("price_eok")
        np = new[k].get("price_eok")
        if op is not None and np is not None and op != np:
            price_changes.append({
                "article_no": k,
                "complex_name": new[k]["complex_name"],
                "old_price_eok": op,
                "new_price_eok": np,
                "delta_eok": round(np - op, 4),
                "direction": "down" if np < op else "up",
                "area_exclusive": new[k].get("area_exclusive"),
                "floor": new[k].get("floor"),
            })

    return {
        "added": added,
        "removed": removed,
        "price_changes": price_changes,
    }


async def crawl():
    data = load_data()
    collected_at = now_kst().isoformat(timespec="seconds")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        snapshots = data.get("snapshots", [])

        for idx, complex_info in enumerate(COMPLEXES):
            name = complex_info["name"]
            complex_no = complex_info["complex_no"]

            print(f"[{idx+1}/{len(COMPLEXES)}] {name}")

            # 먼저 네이버 단지 페이지를 열어 세션을 만든다.
            await page.goto(
                complex_info["naver_url"],
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(2500)

            articles = None
            last_error = None

            for attempt in range(3):
                try:
                    articles = await fetch_articles(page, complex_no)
                    break
                except Exception as e:
                    last_error = e
                    print(f"  retry {attempt+1}/3: {e}")
                    await page.wait_for_timeout(4000 * (attempt + 1))

            if articles is None:
                print(f"  FAILED: {last_error}")
                continue

            snapshot = make_snapshot(
                name,
                articles,
                collected_at,
            )

            # 같은 단지의 마지막 snapshot과 비교
            old_snapshot = next(
                (
                    s for s in reversed(snapshots)
                    if s.get("complex_name") == name
                ),
                None,
            )

            changes = calculate_changes(old_snapshot, snapshot)
            snapshot["changes_from_previous"] = changes

            # 이력에 추가
            snapshots.append(snapshot)

            print(
                f"  collected={snapshot['listing_count']} "
                f"added={len(changes['added'])} "
                f"removed={len(changes['removed'])} "
                f"price_changes={len(changes['price_changes'])}"
            )

            # 요청 간격
            if idx < len(COMPLEXES) - 1:
                await page.wait_for_timeout(2500)

        await browser.close()

    # 오래된 snapshot 제거
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]

    data["updated_at"] = collected_at
    data["target_price_eok"] = TARGET_PRICE_EOK
    data["snapshots"] = snapshots

    save_data(data)
    print(f"Saved: {DATA_PATH}")


if __name__ == "__main__":
    asyncio.run(crawl())
