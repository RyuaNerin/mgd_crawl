"""
만든이들
- 필모렐 (Discord: @pilmorel_73175)
- 류아네린 (RyuaNerin, ryuar.in)


pip install requests beautifulsoup4 selenium webdriver-manager selenium_stealth
"""

import json
import logging
import os.path
import re
import warnings
from base64 import b64decode
from datetime import datetime, timedelta
from posixpath import relpath
from time import sleep
from typing import Callable, Final
from urllib.parse import parse_qsl, unquote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from flask import request
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.remote_connection import LOGGER
from selenium_stealth import stealth
from wakepy import keep
from webdriver_manager.chrome import ChromeDriverManager

from version import VERSION

LOGGER.setLevel(logging.CRITICAL)

REPOSITORY_URL: Final = (
    "https://api.github.com/repos/RyuaNerin/mgd_crawl/releases/latest"
)

TGD_HOST: Final = "tgd.kr"
TGD_URL: Final = "https://tgd.kr"


# tag manager 같은 필요 없는 항목 다운로드 하지 않도록
IGNORE_HOSTS: Final = [
    "securepubads.g.doubleclick.net",
    "www.google.com",
    "www.googleoptimize.com",
    "www.googletagmanager.com",
    "www.google-analytics.com",
    "www.googleadservices.com",
    "www.gstatic.com",
    "tpc.googlesyndication.com",
]


def try_except(func: Callable):
    try:
        func()
    except Exception:
        pass


class Url(object):
    """A url object that can be compared with other url orbjects
    without regard to the vagaries of encoding, escaping, and ordering
    of parameters in query strings."""

    def __init__(self, url):
        parts = urlparse(url)
        _query = frozenset(parse_qsl(parts.query))
        _path = unquote_plus(parts.path)
        parts = parts._replace(query=_query, path=_path)
        self.parts = parts

    def __eq__(self, other):
        return self.parts == other.parts

    def __hash__(self):
        return hash(self.parts)


class Crawler:
    def __init__(self, tgd_id: str):
        self.tgd_id = tgd_id
        self.driver: webdriver.Chrome = None  # type: ignore
        self.driver_logs: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close_driver()

    def write_info(self, article_info: str):
        filename = f"{self.tgd_id}_info.txt"
        if os.path.isfile(filename):
            with open(filename, "a", encoding="utf-8") as fs:
                fs.write(article_info + "\n")
        else:
            with open(filename, "w", encoding="utf-8") as fs:
                fs.write("번호 | 일시 | 카테고리 | 제목 | 글쓴이\n")
                fs.write(article_info + "\n")

    def filter_downloaded(self, article_list: list[tuple[int, bool]]) -> list[int]:
        archived: set[int] = set()

        ## 중복이면 True, 중복이 아니면 False
        filename = f"{self.tgd_id}_info.txt"
        if os.path.isfile(filename):
            with open(filename, "r", encoding="utf-8") as fs:
                for line in fs:
                    try:
                        archived.add(int(line.split("|")[0].strip()))
                    except:  # noqa: E722
                        pass

        return [
            x[0]
            for x in sorted(
                [x for x in article_list if x[0] not in archived],
                key=lambda x: (not x[1], -x[0]),
            )
        ]

    def new_driver(self, headless=True):
        self.close_driver()

        self.driver_logs.clear()

        options = webdriver.ChromeOptions()
        options.add_experimental_option(
            "excludeSwitches", ["enable-automation", "enable-logging"]
        )
        options.add_argument("window-size=1920x1080")
        options.add_argument("--log-level=3")

        if headless:
            options.add_argument("headless")

        options.enable_downloads = True
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        self.driver = webdriver.Chrome(
            options=options, service=ChromeService(ChromeDriverManager().install())
        )
        self.driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})

        self.driver.delete_all_cookies()
        stealth(
            self.driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

    def close_driver(self):
        if self.driver:
            try_except(lambda: self.driver.close())
            try_except(lambda: self.driver.quit())
            self.driver = None  # type: ignore

    def get_cached_content(self, url: str) -> str | None:
        logs = self.driver.get_log("performance")
        self.driver_logs.extend(logs)

        target_url = Url(url)

        for log in self.driver_logs:
            message = log["message"]
            if "Network.responseReceived" in message:
                params = json.loads(message)["message"].get("params")
                if params:
                    response = params.get("response")
                    if response and target_url == Url(response["url"]):
                        body = self.driver.execute_cdp_cmd(
                            "Network.getResponseBody",
                            {"requestId": params["requestId"]},
                        )
                        return body["body"]

        return None

    def navigate_and_check_captcha(self, url: str) -> None:
        MAX_WAIT: Final = 30

        print(url)
        self.driver.get(url)

        first = True
        retried = 0

        while True:
            try:
                self.driver.find_element(By.ID, "main-menu")
                return
            except:  # noqa: E722
                pass

            if first:
                first = False
                print("captcha 감지! 확인해주세요!")

                retried = MAX_WAIT
            sleep(1)

            retried += 1
            try:
                _ = self.driver.window_handles
            except:  # noqa: E722
                retried = MAX_WAIT

            if retried >= MAX_WAIT:
                retried = 0
                self.new_driver(False)
                self.driver.get(url)

    def download_list(self, page_number: int) -> tuple[list[int], bool]:
        page_url = f"{TGD_URL}/s/{self.tgd_id}/page/{page_number}"

        article_list: list[tuple[int, bool]] = []  # id, notice

        self.new_driver()
        self.navigate_and_check_captcha(page_url)

        # remove some elements
        self.clear_ads()

        soup = BeautifulSoup(self.driver.page_source, "html.parser")

        row: Tag
        for row in soup.find_all("div", class_="article-list-row"):
            # 비밀글 제외
            if row.find_all("i", class_="fa fa-lock"):
                continue

            id = int(row["id"].replace("article-list-row-", ""))  # type: ignore
            article_list.append((id, "notice" in row["class"]))

        self.save_html(soup, f"page_{page_number}.html", page_url)

        # 중복 항목 제거
        article_no_list = self.filter_downloaded(article_list)

        ## 다음 페이지 있으면 True, 다음 페이지 없으면 False
        next = soup.find("a", {"rel": "next"}) is not None

        self.close_driver()

        return article_no_list, next

    def download_artice(self, article_no: int):
        article_url = f"{TGD_URL}/s/{self.tgd_id}/{article_no}"

        self.new_driver()
        self.navigate_and_check_captcha(article_url)

        # remove some elements
        self.clear_ads()

        soup = BeautifulSoup(self.driver.page_source, "html.parser")

        article_time: str
        article_category: str
        article_title: str
        article_writer: str

        try:
            article_time = soup.select_one("span#article-time > span").text  # type: ignore
        except:  # noqa: E722
            return

        article_head = soup.select_one("div#article-info > h2").text.split("\n")  # type: ignore
        if len(article_head) == 2:
            article_category = ""
            article_title = article_head[1].strip()
        else:
            article_category = article_head[1].strip()
            article_title = article_head[2].strip()

        article_writer = soup.select_one("div#article-info-writer > strong").text  # type: ignore

        article_info = " | ".join(
            [
                str(article_no),
                article_time,
                article_category,
                article_title,
                article_writer,
            ]
        )
        print(article_info)

        ####################################################################################################

        self.save_html(soup, f"{article_no}.html", article_url)

        self.write_info(article_info)

        self.close_driver()

    def clear_ads(self) -> None:
        # 광고제거
        # adguard 및 List-KR 필터를 기반으로 한다.
        for _ in range(3):
            count = self.driver.execute_script(
                """
                (function() {
                    function remove_csspath(path) {
                        try {
                            var elements = $(path);
                            for (var element of elements) element.parentNode.removeChild(element);
                            
                            return elements.length;
                        } catch (e) {
                            return 0;
                        }
                    }

                    //////////////////////////////////////////////////

                    var count = 0;

                    // List-KR
                    // tgd.kr#?#div[style*="padding:"]:has(div[style] div[style]:contains(AD))
                    count += remove_csspath('div[style*="padding:"]:has(div[style] div[style]:contains(AD))');

                    // List-KR
                    // tgd.kr,dpg.danawa.com##div[id*="-ad-"]
                    count += remove_csspath('div[id*="-ad-"]');

                    // List-KR
                    // tgd.kr#?#div[style^="display:"]:has(div[style*="width:"] > div[id^="div-gpt-ad-"])
                    count += remove_csspath('div[style^="display:"]:has(div[style*="width:"] > div[id^="div-gpt-ad-"])');

                    // List-KR
                    // tgd.kr###main-menu div[style][align]
                    count += remove_csspath('#main-menu div[style][align]');

                    // Adguard base filter
                    // ##[data-id^="div-gpt-ad"]
                    count += remove_csspath('[data-id^="div-gpt-ad"]');

                    return count;
                })()
                """
            )
            if count == 0:
                break

        def remove(xpath: str) -> None:
            try:
                elements = self.driver.find_elements(By.XPATH, xpath)
                for element in elements:
                    self.driver.execute_script(
                        "arguments[0].parentNode.removeChild(arguments[0]);",
                        element,
                    )
            except Exception as ex:  # noqa: E722
                print(ex)
                pass

        # 위아래
        remove("//body/header")
        remove("//body/footer")

        # 서비스 종료 알림
        remove("//body/div[@class='container']")

        # 약관
        remove("//body/div[@id='term-modal']")

        # 사이드 메뉴
        remove("//body/div[@id='side-menu']")

        # google tag manager
        remove("//body/noscript")

    def save_html(
        self,
        soup: BeautifulSoup,
        html_path: str,
        base_url: str,
    ):
        base_dir = self.tgd_id
        html_dir = os.path.dirname(os.path.join(base_dir, html_path))
        resource_dir = os.path.join(base_dir, "resources")

        ignore_resource_prefix = [
            f"https://tgd.kr/s/{self.tgd_id}/",
        ]

        tags: list[Tag] = list(
            set(soup.find_all(["meta", "img", "link", "script", "source"]))
        )
        for tag in tags:
            match tag.name:
                case "meta":
                    if tag.has_attr("content"):
                        resource_url = urljoin(base_url, str(tag.get("content")))
                        if any(
                            resource_url.startswith(prefix)
                            for prefix in ignore_resource_prefix
                        ):
                            continue

                        resource_path, downloaded = self.download_resource(
                            resource_url,
                            resource_dir,
                            base_url,
                        )
                        if resource_path:
                            tag["content"] = relpath(resource_path, html_dir)

                case "img":
                    if tag.has_attr("src"):
                        resource_url = urljoin(base_url, str(tag.get("src")))
                        resource_path, downloaded = self.download_resource(
                            resource_url,
                            resource_dir,
                            base_url,
                        )
                        if resource_path:
                            tag["src"] = relpath(resource_path, html_dir)

                    if tag.has_attr("onerror") and "this.src='https://upload.tgd.kr/icon/nologin.png'" in tag.get("onerror"):  # type: ignore
                        tag["onerror"] = ""

                case "source":
                    if tag.has_attr("src"):
                        resource_url = urljoin(base_url, str(tag.get("src")))
                        resource_path, downloaded = self.download_resource(
                            resource_url,
                            resource_dir,
                            base_url,
                        )
                        if resource_path:
                            tag["src"] = relpath(resource_path, html_dir)

                case "script":
                    if tag.has_attr("src"):
                        resource_url = urljoin(base_url, str(tag.get("src")))
                        resource_path, downloaded = self.download_resource(
                            resource_url,
                            resource_dir,
                            base_url,
                        )
                        if resource_path:
                            tag["src"] = relpath(resource_path, html_dir)

                case "link":
                    if tag.has_attr("href"):  # type: ignore
                        resource_url = urljoin(base_url, str(tag.get("href")))
                        if any(
                            resource_url.startswith(prefix)
                            for prefix in ignore_resource_prefix
                        ):
                            continue

                        resource_path, downloaded = self.download_resource(
                            resource_url,
                            resource_dir,
                            base_url,
                        )
                        if resource_path:
                            tag["href"] = relpath(resource_path, html_dir)

                            # CSS
                            if downloaded and (tag.has_attr("rel") and "stylesheet" in tag.get("rel")):  # type: ignore
                                with open(resource_path, "r", encoding="utf-8") as fs:
                                    css_content = fs.read()
                                with open(resource_path, "w", encoding="utf-8") as fs:
                                    fs.write(
                                        self.process_css_content(
                                            css_content,
                                            resource_url,
                                            resource_dir,
                                            css_path=resource_path,
                                        )
                                    )

        # 다른 게시글로 옮겨갈 수 있도록 처리
        for tag in soup.find_all("a"):
            if tag.has_attr("href"):
                href = urlparse(urljoin(base_url, str(tag.get("href"))))

                # 게시글
                if href.hostname == TGD_HOST and href.path.startswith(
                    f"/s/{self.tgd_id}/"
                ):
                    href_article_no = href.path[len(f"/s/{self.tgd_id}/") :]
                    tag["href"] = f"{href_article_no}.html"

                # 페이지
                if href.hostname == TGD_HOST and href.path.startswith(
                    f"/s/{self.tgd_id}/page/"
                ):
                    page_url = f"page_{os.path.basename(href.path)}"
                    if not page_url.endswith(".html") and not page_url.endswith(".htm"):
                        page_url += ".html"
                    tag["href"] = page_url

        # 타이틀 처리
        try:
            soup.find("h1").find("a")["href"] = "page_1.html"  # type: ignore
        except:  # noqa: E722
            pass

        # 저장
        resource_path = os.path.join(self.tgd_id, html_path)
        os.makedirs(os.path.dirname(resource_path), exist_ok=True)
        with open(resource_path, "w", encoding="utf-8") as fs:
            fs.write(str(soup))

        # Process inline styles
        for tag in soup.find_all(style=True):
            tag["style"] = self.process_css_content(
                str(tag.get("style")), base_url, html_dir
            )

    def download_resource(
        self, resource_url: str, resource_dir: str, webpage_url: str
    ) -> tuple[str | None, bool]:
        if resource_url.startswith("//"):
            resource_url = f"https:{resource_url}"
        parsed_url = urlparse(resource_url)
        if parsed_url.scheme not in ["http", "https"] or not parsed_url.netloc:
            return None, False

        # tag manager 같은 필요 없는 항목 다운로드 하지 않도록
        if parsed_url.hostname in IGNORE_HOSTS:
            ext = os.path.splitext(parsed_url.path)[1]
            filepath = os.path.join(resource_dir, f"ignored-content{ext}")
            if not os.path.exists(filepath):
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, "w") as fs:
                    fs.write("")

            return filepath, False

        # tgd_id/resources/hostname/path
        filepath: str = os.path.join(resource_dir, parsed_url.hostname, parsed_url.path.lstrip("/") or "index.html").replace("\\", "/")  # type: ignore

        if os.path.exists(filepath):
            return filepath, False

        # 캐시에서 가져오기
        cached_content = self.get_cached_content(resource_url)
        if cached_content:
            # print(f"resource from chrome: {resource_url}")

            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as fs:
                try:
                    fs.write(b64decode(cached_content))
                except:  # noqa: E722
                    fs.write(cached_content.encode("utf-8"))
            return filepath, True

        # requests 써서 가져오기
        try:
            response = requests.get(resource_url, headers={"Referer": webpage_url})
            if response.status_code == 200:
                # print(f"resource from requests: {resource_url}")

                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, "wb") as fs:
                    fs.write(response.content)

                return filepath, True
            else:
                print(f"failed to download resource: {resource_url}")
        except Exception as e:
            print(f"Error downloading {resource_url}: {e}")

        return None, False

    def process_css_content(
        self,
        css_content: str,
        webpage_url: str,
        out_dir: str,
        css_path: str | None = None,
    ) -> str:
        def url_replacer(match):
            url = match.group(1)
            full_url = urljoin(webpage_url, url.strip("'\""))
            downloaded_path, _ = self.download_resource(full_url, out_dir, webpage_url)
            if downloaded_path:
                # relative path...
                url_new = (
                    os.path.relpath(downloaded_path, os.path.dirname(css_path))
                    if css_path
                    else downloaded_path
                ).replace("\\", "/")
                return f"url('{url_new}')"

            return match.group(0)

        # Replace urls in the CSS content
        css_content = re.sub(r"url\((.*?)\)", url_replacer, css_content)
        return css_content

    def process_script_content(self, script_content: str, base_url: str, out_dir: str):
        # 저장할 때 발생하는 일부 오류 수정...
        # todo
        return script_content


def save_progress(tgd_id: str, page: int, next: bool, remains: list[int] | None):
    file = f"{tgd_id}.progress"
    with open(file, "w", encoding="utf-8") as fs:
        fs.write(
            "\n".join(
                [str(page), "1" if next else "0"] + [str(x) for x in remains]
                if remains
                else []
            )
        )


def load_progress(tgd_id: str) -> tuple[int, bool, list[int]] | None:
    file = f"{tgd_id}.progress"
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as fs:
            lines = fs.readlines()
            page = int(lines[0])
            next = lines[1] == "1"
            page_numbers = [int(x) for x in lines[2:]]

            return page, next, page_numbers

    return None


def del_progress():
    file = f"{tgd_id}.progress"
    if os.path.exists(file):
        os.remove(file)


def check_update():
    try:
        u = requests.get(REPOSITORY_URL).json()

        if u["tag_name"] != VERSION:
            print(
                f"""새로운 버전이 있습니다
현재 버전 : {VERSION}
새로운 버전 : {u['tag_name']}
다운로드: {u['html_url']}"""
            )

    except:
        pass


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    
    check_update()

    print(
        """안녕하세요, 미게더 크롤러입니다.
트게더 서비스 종료에 따른 게시물 백업을 도와드립니다."""
    )

    tgd_id = input(
        """트게더 게시판 주소를 입력해 주세요
예시) https://tgd.kr/s/givemecs 에서 givemecs
기본값은 미녕이데려오께 트게더입니다.
>"""
    )
    if tgd_id == "":
        tgd_id = "givemecs"

    wait_seconds = input(
        """대기 시간을 초단위로 입력하세요.
최소값 (기본값)은 5초입니다.
>"""
    )
    try:
        wait_seconds = max(int(wait_seconds), 5)
    except Exception:
        wait_seconds = 5

    default = (1, True, None)
    (page_number, saved_next, saved_article_no_list) = default
    progress = load_progress(tgd_id)
    if progress:
        (page_number, saved_next, saved_article_no_list) = progress

        p = input(
            f"""트게더 게시판 주소 : {tgd_id}
페이지 : {page_number}
작업 : {'페이지 목록 가져오기' if not saved_article_no_list else f'게시글 가져오기 ({len(saved_article_no_list)} 개)'}
-------------------------
이전 작업을 이어서 진행합니다.
작업을 취소하려면 N을 입력해주세요.
>""",
        )
        if p == "n" or p == "N":
            (page_number, saved_next, saved_article_no_list) = default
            del_progress()

    ## 페이지 테스트용
    # page_number = 332

    with keep.running(), Crawler(tgd_id) as crawler:
        while next:
            if not saved_article_no_list or len(saved_article_no_list) == 0:
                print(f"{page_number} 페이지 목록 다운로드 중...")
                retries = 0
                while True:
                    try:
                        article_no_list, next = crawler.download_list(page_number)
                        break
                    except Exception as ex:
                        retries += 1
                        if retries == 3:
                            raise ex
                        else:
                            print(f"이지 목록 다운로드 실패: {ex}")
                        pass

                print(f"{page_number} 페이지 목록 다운로드 완료")

                save_progress(tgd_id, page_number, next, article_no_list)
            else:
                article_no_list, next = saved_article_no_list, saved_next
            saved_article_no_list = None

            print(f"{page_number} 페이지 게시물 다운로드 중...")

            article_no_list_len = len(article_no_list)

            for idx, article_no in enumerate(article_no_list):
                next_time = datetime.now() + timedelta(seconds=wait_seconds)

                print(f"게시물 다운로드 중... {idx + 1} / {len(article_no_list)} ")
                retries = 0
                while True:
                    try:
                        crawler.download_artice(article_no)
                        break
                    except Exception as ex:
                        retries += 1
                        if retries == 3:
                            raise ex
                        else:
                            print(f"이지 목록 다운로드 실패: {ex}")
                        pass
                print("게시물 다운로드 완료")

                save_progress(tgd_id, page_number, next, article_no_list[idx + 1 :])

                if idx + 1 < article_no_list_len:
                    sleep((datetime.now() - next_time).total_seconds())

            print(f"{page_number} 페이지 게시물 다운로드 완료!")

            page_number = page_number + 1
            save_progress(tgd_id, page_number, next, None)

        del_progress()
        print("모든 게시물 다운로드 완료!")
