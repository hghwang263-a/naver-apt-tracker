import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import COMPLEXES, TARGET_PRICE_EOK, MAX_SNAPSHOTS


DATA_FILE = Path(__file__).with_name("data.json")
BASE_URL = "https://new.land.naver.com"
API_URL = BASE_URL + "/api/articles/complex/{complex_no}"


def parse_price(price_text):
    """Convert Naver Korean price text to 억 units."""
    if not price_text:
        return None

    text = str(price_text).replace(",", "").strip()

    # Examples:
    # 10억 3,000 -> 10.3
    # 10억 -> 10.0
    # 9억 8,000 -> 9.8
    m = re.search(r"(\d+(?:\.\d+)?)\s*억(?:\s*(\d+))?", text)
    if m:
        eok = float(m.group(1))
        man = int(m.group(2) or 0)
        return eok + man / 10000.0

    # Fallback for numeric strings already expressed in 억
    try:
        return float(text)
    except ValueError:
        return None


def normalize_article(article, complex_name, complex_no):
    price_text = (
        article.get("dealOrWarrantPrc")
        or article.get("dealPrc")
        or article.get("price")
        or ""
    )

    article_no = (
        article.get("articleNo")
        or article.get("atclNo")
        or article.get("id")
    )

    return {
        "article_no": str(article_no) if article_no is not None else "",
        "complex_no": str(complex_no),
        "complex_name": complex_name,
        "price_text": str(price_text),
        "price_eok": parse_price(price_text),
        "article_name": article.get("articleName") or article.get("atclNm") or "",
        "area_name": article.get("areaName") or article.get("spc1") or "",
        "floor": article.get("floorInfo") or article.get("flrInfo") or "",
        "direction": article.get("direction") or "",
        "confirm_date": article.get("articleConfirmYmd") or article.get("atclCfmYmd") or "",
        "trade_type": article.get("tradeTypeName") or article.get("tradTpNm") or "",
        "raw": article,
    }


def extract_articles(payload):
    """Handle the common Naver API response shapes."""
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    for key in ("articleList", "articles", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    # Some responses nest the article list.
    for value in payload.values():
        if isinstance(value, dict):
            result = extract_articles(value)
            if result:
                return result
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            if any(
                k in value[0]
                for k in ("articleNo", "atclNo", "articleName", "atclNm")
            ):
                return value

    return []


def fetch_complex(page, complex_name, complex_no):
    """Warm the Naver session, then fetch sale listings from the internal API."""
    page_url = f"{BASE_URL}/complexes/{complex_no}"

    print(f"\n[{complex_name}] warming Naver session: {page_url}")

    # The page itself is only used to establish a browser session.
    # Do not wait for DOMContentLoaded because Naver can keep the page
    # loading indefinitely in a headless GitHub Actions environment.
    try:
        page.goto(
            page_url,
            wait_until="commit",
            timeout=60000,
        )
        print(f"[OK] page commit: {complex_name}")
    except PlaywrightTimeoutError as e:
        print(f"[WARN] page warm-up timeout for {complex_name}: {e}")
    except Exception as e:
        print(f"[WARN] page warm-up failed for {complex_name}: {e}")

    time.sleep(2)

    all_articles = []
    seen = set()

    # Naver's internal API is not an official public API, so response
    # structure / access can change. Keep the request modest.
    for page_no in range(1, 31):
        params = {
            "realEstateType": "APT",
            "tradeType": "A1",
            "tag": "::::::::",
            "rentPrc": "",
            "priceType": "RETAIL",
            "areaType": "",
            "price": "",
            "direction": "",
            "complexNo": str(complex_no),
            "buildingNo": "",
            "minPyeong": "",
            "maxPyeong": "",
            "recentlyViewed": "",
            "sameAddressGroup": "false",
            "page": str(page_no),
        }

        try:
            response = page.request.get(
                API_URL.format(complex_no=complex_no),
                params=params,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": page_url,
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                },
                timeout=30000,
            )

            print(f"[API] {complex_name} page={page_no} status={response.status}")

            if response.status != 200:
                print(f"[WARN] API response status {response.status}")
                break

            try:
                payload = response.json()
            except Exception:
                print("[WARN] API response was not valid JSON")
                break

            raw_articles = extract_articles(payload)

            if not raw_articles:
                print(f"[INFO] no more articles at page {page_no}")
                break

            added_this_page = 0

            for article in raw_articles:
                item = normalize_article(article, complex_name, complex_no)
                key = item["article_no"] or (
                    item["price_text"],
                    item["article_name"],
                    item["area_name"],
                    item["floor"],
                )

                if key in seen:
                    continue

                seen.add(key)
                all_articles.append(item)
                added_this_page += 1

            print(
                f"[OK] page={page_no}, "
                f"raw={len(raw_articles)}, new={added_this_page}, "
                f"total={len(all_articles)}"
            )

            # If fewer than a typical full page arrived, there is usually
            # nothing useful beyond it.
            if len(raw_articles) < 20:
                break

            time.sleep(0.5)

        except Exception as e:
            print(f"[WARN] API request failed on page {page_no}: {e}")
            break

    return all_articles


def load_data():
    if not DATA_FILE.exists():
        return {
            "updated_at": None,
            "target_price_eok": TARGET_PRICE_EOK,
            "snapshots": [],
        }

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("data.json root must be an object")

        data.setdefault("updated_at", None)
        data.setdefault("target_price_eok", TARGET_PRICE_EOK)
        data.setdefault("snapshots", [])
        return data

    except Exception as e:
        print(f"[WARN] Could not read data.json: {e}")
        return {
            "updated_at": None,
            "target_price_eok": TARGET_PRICE_EOK,
            "snapshots": [],
        }


def article_key(article):
    return str(article.get("article_no") or "")


def calculate_changes(previous_articles, current_articles):
    previous = {
        article_key(x): x
        for x in previous_articles
        if article_key(x)
    }
    current = {
        article_key(x): x
        for x in current_articles
        if article_key(x)
    }

    added = [current[k] for k in current.keys() - previous.keys()]
    removed = [previous[k] for k in previous.keys() - current.keys()]

    price_changes = []

    for key in current.keys() & previous.keys():
        old_price = previous[key].get("price_eok")
        new_price = current[key].get("price_eok")

        if (
            old_price is not None
            and new_price is not None
            and abs(float(old_price) - float(new_price)) > 1e-9
        ):
            price_changes.append(
                {
                    "article_no": key,
                    "old_price_eok": old_price,
                    "new_price_eok": new_price,
                    "old_price_text": previous[key].get("price_text", ""),
                    "new_price_text": current[key].get("price_text", ""),
                    "complex_name": current[key].get("complex_name", ""),
                }
            )

    return added, removed, price_changes


def main():
    data = load_data()
    previous_snapshot = data["snapshots"][-1] if data["snapshots"] else None
    previous_articles = (
        previous_snapshot.get("articles", [])
        if previous_snapshot
        else []
    )

    all_articles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        try:
            for complex_name, complex_info in COMPLEXES.items():
                # Support either:
                # {"complex_no": "8194"}
                # or simply {"complex_no": ...} style config.
                if isinstance(complex_info, dict):
                    complex_no = str(complex_info["complex_no"])
                else:
                    complex_no = str(complex_info)

                try:
                    articles = fetch_complex(
                        page,
                        complex_name,
                        complex_no,
                    )
                    all_articles.extend(articles)
                    print(
                        f"[SUMMARY] {complex_name}: "
                        f"{len(articles)} listings"
                    )
                except Exception as e:
                    print(
                        f"[ERROR] {complex_name} failed: {type(e).__name__}: {e}"
                    )

        finally:
            browser.close()

    if not all_articles:
        # Do not overwrite good historical data with an empty snapshot
        # when Naver temporarily blocks or changes its API.
        raise RuntimeError(
            "No apartment listings were collected. "
            "Naver may have blocked the request or changed the API."
        )

    added, removed, price_changes = calculate_changes(
        previous_articles,
        all_articles,
    )

    now = datetime.now(timezone.utc).astimezone().isoformat()

    snapshot = {
        "timestamp": now,
        "articles": all_articles,
        "added": added,
        "removed": removed,
        "price_changes": price_changes,
    }

    data["updated_at"] = now
    data["target_price_eok"] = TARGET_PRICE_EOK
    data["snapshots"].append(snapshot)
    data["snapshots"] = data["snapshots"][-MAX_SNAPSHOTS:]

    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(
        f"\nDONE: {len(all_articles)} total listings, "
        f"{len(added)} added, {len(removed)} removed, "
        f"{len(price_changes)} price changes"
    )


if __name__ == "__main__":
    main()
