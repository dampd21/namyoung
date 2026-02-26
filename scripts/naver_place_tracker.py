"""
네이버 플레이스 순위 추적 및 대표키워드 수집
- Selenium으로 브라우저 세션/쿠키 획득 후 GraphQL API 호출
- 키워드별 순위 추적
- 업체 상세 정보 (리뷰수, 저장수 등)
- 대표키워드 및 검색량 조회
"""

import subprocess
import sys

def ensure_packages():
    required = ['selenium', 'requests']
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            print(f"[INSTALL] {pkg} 설치 중...", flush=True)
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])

ensure_packages()

import requests
import json
import base64
import os
import re
import time
import hashlib
import hmac as hmac_module
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class NaverPlaceTracker:
    def __init__(self):
        self.graphql_url = "https://api.place.naver.com/graphql"
        self.session = requests.Session()
        self.cookies_ready = False
        self.driver = None

    def _find_chromedriver(self):
        env_path = os.environ.get("CHROMEDRIVER_PATH")
        if env_path and os.path.isfile(env_path):
            print(f"[CHROME] ChromeDriver (env): {env_path}", flush=True)
            return env_path

        which_path = shutil.which("chromedriver")
        if which_path:
            print(f"[CHROME] ChromeDriver (which): {which_path}", flush=True)
            return which_path

        common_paths = [
            "/usr/local/bin/chromedriver",
            "/usr/bin/chromedriver",
            "/opt/chromedriver/chromedriver",
            "/snap/bin/chromedriver",
        ]
        for p in common_paths:
            if os.path.isfile(p):
                print(f"[CHROME] ChromeDriver (common): {p}", flush=True)
                return p

        try:
            from webdriver_manager.chrome import ChromeDriverManager
            path = ChromeDriverManager().install()
            print(f"[CHROME] ChromeDriver (wdm): {path}", flush=True)
            return path
        except Exception as e:
            print(f"[CHROME] webdriver-manager 실패: {e}", flush=True)

        print("[CHROME] ChromeDriver를 찾을 수 없음, 기본값 사용", flush=True)
        return None

    def _init_browser(self):
        if self.cookies_ready:
            return True

        print("[BROWSER] Selenium 브라우저 초기화 중...", flush=True)

        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            chrome_options.add_argument("--lang=ko-KR")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

            chrome_binary = os.environ.get("CHROME_BIN")
            if chrome_binary and os.path.isfile(chrome_binary):
                chrome_options.binary_location = chrome_binary
                print(f"[CHROME] Chrome binary: {chrome_binary}", flush=True)

            driver_path = self._find_chromedriver()
            if driver_path:
                service = Service(driver_path)
            else:
                service = Service()

            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.set_page_load_timeout(30)
            self.driver.implicitly_wait(5)

            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })

            print("[BROWSER] 네이버 플레이스 페이지 로딩...", flush=True)
            self.driver.get("https://m.place.naver.com/restaurant/list?query=%EC%A7%AC%EB%BD%95")
            time.sleep(3)

            self.driver.get("https://m.place.naver.com/restaurant/1542530224/home")
            time.sleep(3)
            print(f"[BROWSER] 페이지 제목: {self.driver.title}", flush=True)

            browser_cookies = self.driver.get_cookies()
            print(f"[BROWSER] 브라우저 쿠키 수: {len(browser_cookies)}", flush=True)

            for cookie in browser_cookies:
                self.session.cookies.set(
                    cookie['name'],
                    cookie['value'],
                    domain=cookie.get('domain', ''),
                    path=cookie.get('path', '/')
                )

            self.cookies_ready = True
            print("[BROWSER] 초기화 완료!", flush=True)
            return True

        except Exception as e:
            print(f"[BROWSER] 초기화 실패: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return False

    def _close_browser(self):
        if self.driver:
            try:
                self.driver.quit()
                print("[BROWSER] 브라우저 종료", flush=True)
            except Exception:
                pass
            self.driver = None

    def _execute_in_browser(self, keyword, max_results=100):
        if not self.driver:
            if not self._init_browser():
                return None

        print(f"  [BROWSER-EXEC] 브라우저 내 직접 실행: {keyword}", flush=True)

        try:
            current_url = self.driver.current_url or ""
            if "place.naver.com" not in current_url:
                import urllib.parse
                encoded = urllib.parse.quote(keyword)
                self.driver.get(f"https://m.place.naver.com/restaurant/list?query={encoded}")
                time.sleep(3)
        except Exception:
            import urllib.parse
            encoded = urllib.parse.quote(keyword)
            self.driver.get(f"https://m.place.naver.com/restaurant/list?query={encoded}")
            time.sleep(3)

        js_code = """
        var callback = arguments[arguments.length - 1];
        var searchQuery = arguments[0];
        var maxResults = arguments[1];

        fetch('https://api.place.naver.com/graphql', {
            method: 'POST',
            headers: {
                'accept': '*/*',
                'accept-language': 'ko',
                'content-type': 'application/json',
                'origin': 'https://m.place.naver.com',
                'referer': 'https://m.place.naver.com/'
            },
            body: JSON.stringify([{
                "operationName": "getRestaurantList",
                "variables": {
                    "restaurantListInput": {
                        "query": searchQuery,
                        "x": "126.9783882",
                        "y": "37.5666103",
                        "start": 1,
                        "display": maxResults,
                        "isNmap": false,
                        "deviceType": "pc"
                    }
                },
                "query": "query getRestaurantList($restaurantListInput: RestaurantListInput) { restaurants: restaurantList(input: $restaurantListInput) { items { id name category roadAddress phone totalReviewCount blogCafeReviewCount visitorReviewCount visitorReviewScore saveCount } total } }"
            }])
        })
        .then(function(r) { return r.json(); })
        .then(function(data) { callback(JSON.stringify(data)); })
        .catch(function(e) { callback(JSON.stringify({"error": e.message})); });
        """

        try:
            self.driver.set_script_timeout(30)
            result_str = self.driver.execute_async_script(js_code, keyword, max_results)

            if not result_str:
                print(f"  [BROWSER-EXEC] 빈 응답", flush=True)
                return None

            data = json.loads(result_str)

            if isinstance(data, dict) and "error" in data:
                print(f"  [BROWSER-EXEC] JS 에러: {data['error']}", flush=True)
                return None

            if isinstance(data, list) and len(data) > 0:
                items = data[0].get('data', {}).get('restaurants', {}).get('items', [])
                total = data[0].get('data', {}).get('restaurants', {}).get('total', 0)

                if items:
                    print(f"  [BROWSER-EXEC] {len(items)}개 결과 (총 {total}개)", flush=True)
                    return {
                        "success": True,
                        "total": total,
                        "items": items,
                        "method": "browser_exec"
                    }
                else:
                    print(f"  [BROWSER-EXEC] 검색 결과 0개", flush=True)
                    return {
                        "success": True,
                        "total": 0,
                        "items": [],
                        "method": "browser_exec"
                    }

            print(f"  [BROWSER-EXEC] 예상치 못한 응답 형식", flush=True)
            return None

        except Exception as e:
            print(f"  [BROWSER-EXEC] 실행 실패: {e}", flush=True)
            return None

    def search_keyword_ranking(self, keyword, max_results=100):
        result = self._execute_in_browser(keyword, max_results)
        if result and result.get("success"):
            return result
        return {"success": False, "total": 0, "items": []}

    def find_store_rank(self, keyword, place_id):
        result = self.search_keyword_ranking(keyword, max_results=100)

        if not result["success"]:
            return None

        for idx, item in enumerate(result["items"], 1):
            item_id = str(item.get("id", ""))
            if item_id == str(place_id):
                return {
                    "rank": idx,
                    "total": result["total"],
                    "item": item,
                    "method": result.get("method", "unknown")
                }

        return {
            "rank": None,
            "total": result["total"],
            "item": None,
            "method": result.get("method", "unknown")
        }

    def get_review_stats(self, place_id):
        if not self.driver:
            if not self._init_browser():
                return {"success": False}

        try:
            self.driver.get(f"https://m.place.naver.com/restaurant/{place_id}/review/visitor")
            time.sleep(2)
        except Exception:
            pass

        js_code = """
        var callback = arguments[arguments.length - 1];
        var placeId = arguments[0];

        fetch('https://api.place.naver.com/graphql', {
            method: 'POST',
            headers: {
                'accept': '*/*',
                'accept-language': 'ko',
                'content-type': 'application/json',
                'origin': 'https://m.place.naver.com',
                'referer': 'https://m.place.naver.com/restaurant/' + placeId + '/review/visitor'
            },
            body: JSON.stringify([{
                "operationName": "getVisitorReviewStats",
                "variables": {
                    "businessType": "restaurant",
                    "id": placeId
                },
                "query": "query getVisitorReviewStats($id: String, $businessType: String = \\"restaurant\\") { visitorReviewStats(input: {businessId: $id, businessType: $businessType}) { id name review { avgRating totalCount imageReviewCount starDistribution { count score } } analysis { themes { code label count } votedKeyword { details { displayName count } } } visitorReviewsTotal ratingReviewsTotal } }"
            }])
        })
        .then(function(r) { return r.json(); })
        .then(function(data) { callback(JSON.stringify(data)); })
        .catch(function(e) { callback(JSON.stringify({"error": e.message})); });
        """

        try:
            self.driver.set_script_timeout(30)
            result_str = self.driver.execute_async_script(js_code, place_id)

            if not result_str:
                return {"success": False}

            data = json.loads(result_str)

            if isinstance(data, dict) and "error" in data:
                return {"success": False}

            if isinstance(data, list) and len(data) > 0:
                stats = data[0].get('data', {}).get('visitorReviewStats', {})
                if stats:
                    review = stats.get('review', {}) or {}
                    analysis = stats.get('analysis', {}) or {}
                    voted = []
                    if analysis and analysis.get('votedKeyword'):
                        voted = analysis['votedKeyword'].get('details', [])

                    return {
                        "success": True,
                        "avg_rating": review.get('avgRating', 0),
                        "total_reviews": review.get('totalCount', 0),
                        "image_reviews": review.get('imageReviewCount', 0),
                        "star_distribution": review.get('starDistribution', []),
                        "themes": analysis.get('themes', []) if analysis else [],
                        "voted_keywords": voted[:10]
                    }

        except Exception as e:
            print(f"  [ReviewStats] 실패 ({place_id}): {e}", flush=True)

        return {"success": False}

    def get_keyword_search_volume(self, keywords):
        api_key = os.environ.get('NAVER_AD_API_KEY')
        secret_key = os.environ.get('NAVER_AD_SECRET_KEY')
        customer_id = os.environ.get('NAVER_AD_CUSTOMER_ID')

        if not all([api_key, secret_key, customer_id]):
            print("[WARN] 네이버 광고 API 키 없음, 검색량 조회 건너뜀", flush=True)
            return {}

        timestamp = str(int(time.time() * 1000))
        method = "GET"
        path = "/keywordstool"

        sign_str = f"{timestamp}.{method}.{path}"
        signature = hmac_module.new(
            secret_key.encode(),
            sign_str.encode(),
            hashlib.sha256
        ).digest()
        signature = base64.b64encode(signature).decode()

        headers = {
            "X-API-KEY": api_key,
            "X-Customer": customer_id,
            "X-Timestamp": timestamp,
            "X-Signature": signature
        }

        result = {}

        for i in range(0, len(keywords), 5):
            batch = keywords[i:i+5]
            params = {
                "hintKeywords": ",".join(batch),
                "showDetail": "1"
            }

            try:
                response = requests.get(
                    f"https://api.searchad.naver.com{path}",
                    headers=headers,
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()

                for item in data.get('keywordList', []):
                    kw = item.get('relKeyword', '')
                    pc = item.get('monthlyPcQcCnt', 0)
                    mobile = item.get('monthlyMobileQcCnt', 0)

                    if isinstance(pc, str):
                        pc = 10 if '<' in pc else int(pc.replace(',', ''))
                    if isinstance(mobile, str):
                        mobile = 10 if '<' in mobile else int(mobile.replace(',', ''))

                    result[kw] = {
                        "pc": pc,
                        "mobile": mobile,
                        "total": pc + mobile,
                        "comp": item.get('compIdx', '')
                    }

                time.sleep(0.5)

            except Exception as e:
                print(f"[ERROR] 검색량 조회 실패: {e}", flush=True)

        return result


def load_tracking_config():
    config_path = Path("docs/marketing_config.json")

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    default_config = {
        "tracking_keywords": {},
        "store_places": {}
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(default_config, f, ensure_ascii=False, indent=2)

    return default_config


def load_existing_data():
    data_path = Path("docs/marketing_data.json")

    if data_path.exists():
        with open(data_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    return {
        "generated_at": None,
        "tracking_history": {},
        "competitor_analysis": {}
    }


def save_data(data):
    data_path = Path("docs/marketing_data.json")
    data_path.parent.mkdir(parents=True, exist_ok=True)

    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 데이터 저장 완료: {data_path}", flush=True)


def run_daily_tracking():
    print("=" * 60, flush=True)
    print("네이버 플레이스 순위 추적 시작", flush=True)
    print("=" * 60, flush=True)

    tracker = NaverPlaceTracker()
    config = load_tracking_config()
    data = load_existing_data()

    today = datetime.now().strftime("%Y-%m-%d")
    weekday = ["월", "화", "수", "목", "금", "토", "일"][datetime.now().weekday()]

    print(f"날짜: {today} ({weekday})", flush=True)

    tracking_keywords = config.get("tracking_keywords", {})
    store_places = config.get("store_places", {})

    if not tracking_keywords:
        print("[WARN] 추적 키워드가 설정되지 않았습니다.", flush=True)
        print("[INFO] docs/marketing_config.json 파일을 확인하세요.", flush=True)

    success_count = 0
    fail_count = 0

    try:
        if not tracker._init_browser():
            print("[ERROR] 브라우저 초기화 실패, 종료", flush=True)
            return

        for store_name, keywords in tracking_keywords.items():
            place_id = store_places.get(store_name, "")

            if not place_id:
                print(f"\n[{store_name}] Place ID 없음, 건너뜀", flush=True)
                continue

            if not keywords:
                continue

            print(f"\n[{store_name}] 추적 중... (Place ID: {place_id})", flush=True)

            review_stats = tracker.get_review_stats(place_id)
            if review_stats.get("success"):
                print(f"  리뷰 통계: 평점 {review_stats.get('avg_rating', 0)}, "
                      f"총 {review_stats.get('total_reviews', 0)}건", flush=True)
            time.sleep(1)

            for keyword in keywords:
                print(f"  키워드: {keyword}", flush=True)

                rank_result = tracker.find_store_rank(keyword, place_id)
                time.sleep(2)

                if rank_result is not None:
                    rank = rank_result.get("rank")
                    item = rank_result.get("item") or {}
                    method = rank_result.get("method", "unknown")

                    history_key = f"{store_name}|{keyword}"

                    if history_key not in data["tracking_history"]:
                        data["tracking_history"][history_key] = {
                            "store_name": store_name,
                            "place_id": place_id,
                            "keyword": keyword,
                            "history": []
                        }

                    today_data = {
                        "date": today,
                        "weekday": weekday,
                        "rank": rank,
                        "blog_reviews": str(item.get("blogCafeReviewCount", "0")),
                        "visitor_reviews": str(item.get("visitorReviewCount", "0")),
                        "save_count": str(item.get("saveCount", "0")),
                        "score": item.get("visitorReviewScore", 0),
                        "method": method
                    }

                    if review_stats.get("success"):
                        today_data["review_stats"] = {
                            "total": review_stats.get("total_reviews", 0),
                            "avg_rating": review_stats.get("avg_rating", 0),
                            "themes": review_stats.get("themes", [])[:5],
                            "voted_keywords": review_stats.get("voted_keywords", [])[:5]
                        }

                    history = data["tracking_history"][history_key]["history"]
                    if not history or history[0].get("date") != today:
                        history.insert(0, today_data)
                        data["tracking_history"][history_key]["history"] = history[:90]
                    else:
                        history[0] = today_data

                    rank_str = f"{rank}위" if rank else "100위 밖"
                    print(f"    -> {rank_str} ({method})", flush=True)
                    success_count += 1
                else:
                    print(f"    -> 조회 실패", flush=True)
                    fail_count += 1

    except Exception as e:
        print(f"[ERROR] 추적 중 오류: {e}", flush=True)
        import traceback
        traceback.print_exc()

    finally:
        tracker._close_browser()

    data["generated_at"] = datetime.now().isoformat()
    save_data(data)

    print("", flush=True)
    print("=" * 60, flush=True)
    print(f"순위 추적 완료! (성공: {success_count}, 실패: {fail_count})", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    run_daily_tracking()
