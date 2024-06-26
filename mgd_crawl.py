"""
만든이들
- 필모렐 (Discord: @pilmorel_73175)
- 류아네린 (RyuaNerin, ryuar.in)


pip install requests beautifulsoup4 selenium webdriver-manager selenium_stealth
"""

import logging
import os.path
import re
import warnings
from posixpath import relpath
from time import sleep
from typing import Final
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.remote_connection import LOGGER
from selenium_stealth import stealth
from webdriver_manager.chrome import ChromeDriverManager

LOGGER.setLevel(logging.CRITICAL)


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


def write_info(tgd_id: str, article_info: str):
    filename = f"{tgd_id}_info.txt"
    if os.path.isfile(filename):
        with open(filename, "a", encoding="utf-8") as fs:
            fs.write(article_info + "\n")
    else:
        with open(filename, "w", encoding="utf-8") as fs:
            fs.write("번호 | 일시 | 카테고리 | 제목 | 글쓴이\n")
            fs.write(article_info + "\n")


def filter_downloaded(tgd_id: str, article_list: list[tuple[int, bool]]) -> list[int]:
    archived: set[int] = set()

    ## 중복이면 True, 중복이 아니면 False
    filename = f"{tgd_id}_info.txt"
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


def new_driver(headless=True) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument("headless")
    options.add_argument("window-size=1920x1080")
    options.add_argument("--log-level=3")
    # options.add_argument("--proxy-server=127.0.0.1:50000")

    driver = webdriver.Chrome(
        options=options,
        service=ChromeService(ChromeDriverManager().install()),
    )

    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    driver.delete_all_cookies()
    driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})

    return driver


def check_captcha(driver: webdriver.Chrome) -> bool:
    try:
        driver.find_element(By.ID, "main-menu")
        return True
    except:  # noqa: E722
        return False


def wait_captcha(driver: webdriver.Chrome) -> None:
    first = True

    while not check_captcha(driver):
        if first:
            first = False
            print("captcha 감지! 확인해주세요!")
        sleep(1)


def get_article_no_list(tgd_id: str, page_number: int) -> tuple[list[int], bool]:
    url = f"{TGD_URL}/s/{tgd_id}/page/{page_number}"

    article_list: list[tuple[int, bool]] = []  # id, notice

    with new_driver() as driver:
        print(url)
        driver.get(url)
        if not check_captcha(driver):
            driver.close()
            driver = new_driver(False)
            driver.get(url)
            wait_captcha(driver)

        soup = BeautifulSoup(driver.page_source, "html.parser")

        row: Tag
        for row in soup.find_all("div", class_="article-list-row"):
            id = int(row["id"].replace("article-list-row-", ""))  # type: ignore
            article_list.append((id, "notice" in row["class"]))

    # 중복 항목 제거
    article_no_list = filter_downloaded(tgd_id, article_list)

    ## 다음 페이지 있으면 True, 다음 페이지 없으면 False
    next = soup.find("a", {"rel": "next"}) is not None

    return article_no_list, next


def clean(driver: webdriver.Chrome) -> None:
    # 광고제거
    # adguard 및 List-KR 필터를 기반으로 한다.
    for _ in range(3):
        count = driver.execute_script(
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
            elements = driver.find_elements(By.XPATH, xpath)
            for element in elements:
                driver.execute_script(
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


def download_artice(tgd_id: str, article_no: int):
    article_url = f"{TGD_URL}/s/{tgd_id}/{article_no}"

    with new_driver() as driver:
        print(article_url)
        driver.get(article_url)
        if not check_captcha(driver):
            driver.close()
            driver = new_driver(False)
            driver.get(article_url)
            wait_captcha(driver)

        # remove some elements
        clean(driver)

        soup = BeautifulSoup(driver.page_source, "html.parser")

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
        write_info(tgd_id, article_info)

        ####################################################################################################

        # mhtml로 저장하는 부분...
        # 광고 차단이나 이런게 안먹혀서 아래 방법 사용함.
        # save_mhtml(driver, tgd_id, article_no)

        save_html(soup, tgd_id, f"{article_no}.html", article_url)


def save_mhtml(driver: webdriver.Chrome, tgd_id: str, article_no: int):
    mhtml = driver.execute_cdp_cmd("Page.captureSnapshot", {})

    os.makedirs(tgd_id, exist_ok=True)
    with open(
        os.path.join(tgd_id, f"{article_no}.mhtml"),
        "w",
        encoding="utf-8",
        newline="",
    ) as fs:
        fs.write(mhtml["data"])


def save_html(soup: BeautifulSoup, tgd_id: str, html_path: str, webpage_url: str):
    out_dir = tgd_id
    out_res_dir = os.path.join(tgd_id, "resources")

    ignore_prefix = [
        f"https://tgd.kr/s/{tgd_id}/",
    ]

    tag: Tag
    for tag in soup.find_all(["meta", "img", "link", "script", "source"]):
        match tag.name:
            case "meta":
                if tag.has_attr("content"):
                    resource_url = urljoin(webpage_url, str(tag.get("content")))
                    if any(resource_url.startswith(prefix) for prefix in ignore_prefix):
                        continue

                    filepath, downloaded = download_resource(
                        resource_url,
                        out_res_dir,
                        webpage_url,
                    )
                    if filepath:
                        tag["content"] = relpath(filepath, tgd_id)

            case "img":
                if tag.has_attr("src"):
                    resource_url = urljoin(webpage_url, str(tag.get("src")))
                    filepath, downloaded = download_resource(
                        resource_url,
                        out_res_dir,
                        webpage_url,
                    )
                    if filepath:
                        tag["src"] = relpath(filepath, tgd_id)

                if tag.has_attr("onerror") and "this.src='https://upload.tgd.kr/icon/nologin.png'" in tag.get("onerror"):  # type: ignore
                    tag["onerror"] = ""

            case "source":
                if tag.has_attr("src"):
                    resource_url = urljoin(webpage_url, str(tag.get("src")))
                    filepath, downloaded = download_resource(
                        resource_url,
                        out_res_dir,
                        webpage_url,
                    )
                    if filepath:
                        tag["src"] = relpath(filepath, tgd_id)

            case "script":
                if tag.has_attr("src"):
                    resource_url = urljoin(webpage_url, str(tag.get("src")))
                    filepath, downloaded = download_resource(
                        resource_url,
                        out_res_dir,
                        webpage_url,
                    )
                    if filepath:
                        tag["src"] = relpath(filepath, tgd_id)

            case "link":
                if tag.has_attr("href"):  # type: ignore
                    resource_url = urljoin(webpage_url, str(tag.get("href")))
                    if any(resource_url.startswith(prefix) for prefix in ignore_prefix):
                        continue

                    filepath, downloaded = download_resource(
                        resource_url,
                        out_res_dir,
                        webpage_url,
                    )
                    if filepath:
                        tag["href"] = relpath(filepath, tgd_id)

                        # CSS
                        if downloaded and (tag.has_attr("rel") and "stylesheet" in tag.get("rel")):  # type: ignore
                            with open(filepath, "r", encoding="utf-8") as fs:
                                css_content = fs.read()
                            with open(filepath, "w", encoding="utf-8") as fs:
                                fs.write(
                                    process_css_content(
                                        css_content,
                                        resource_url,
                                        out_res_dir,
                                        css_path=filepath,
                                    )
                                )

    # 다른 게시글로 옮겨갈 수 있도록 처리
    for tag in soup.find_all("a"):
        if tag.has_attr("href"):
            href = str(tag.get("href"))
            href = urljoin(webpage_url, href)

            href_url = urlparse(href)
            if href_url.path.startswith(f"/s/{tgd_id}/"):
                href_article_no = href_url.path[len(f"/s/{tgd_id}/") :]
                tag["href"] = f"{href_article_no}.html"

    # 저장
    filepath = os.path.join(tgd_id, html_path)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as fs:
        fs.write(str(soup))

    # Process inline styles
    for tag in soup.find_all(style=True):
        tag["style"] = process_css_content(str(tag.get("style")), webpage_url, out_dir)


def download_resource(
    url: str, out_dir: str, webpage_url: str
) -> tuple[str | None, bool]:
    if url.startswith("//"):
        url = f"https:{url}"
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ["http", "https"] or not parsed_url.netloc:
        return None, False

    # tag manager 같은 필요 없는 항목 다운로드 하지 않도록
    if parsed_url.hostname in IGNORE_HOSTS:
        ext = os.path.splitext(parsed_url.path)[1]
        filepath = os.path.join(out_dir, f"ignored-content{ext}")
        if not os.path.exists(filepath):
            with open(filepath, "w") as fs:
                fs.write("")

        return filepath, False

    # tgd_id/resources/hostname/path
    filepath: str = os.path.join(out_dir, parsed_url.hostname, parsed_url.path.lstrip("/") or "index.html").replace("\\", "/")  # type: ignore

    if os.path.exists(filepath):
        return filepath, False

    try:
        response = requests.get(url, headers={"Referer": webpage_url})
        if response.status_code == 200:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as fs:
                fs.write(response.content)

            return filepath, True
        else:
            print(f"failed to download resource: {url} -> {response.status_code}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")

    return None, False


def process_css_content(
    css_content: str, webpage_url: str, out_dir: str, css_path: str | None = None
) -> str:
    def url_replacer(match):
        url = match.group(1)
        full_url = urljoin(webpage_url, url.strip("'\""))
        downloaded_path, _ = download_resource(full_url, out_dir, webpage_url)
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


def process_script_content(script_content: str, base_url: str, out_dir: str):
    # 저장할 때 발생하는 일부 오류 수정...
    # todo
    return script_content


if __name__ == "__main__":
    warnings.filterwarnings("ignore")

    # mp4, jpg 다운로드 테스트용
    # download_artice("givemecs", 69999562) # mp4
    # download_artice("givemecs", 69999555) # jpg

    print(
        "안녕하세요, 미게더 크롤러입니다. 트게더 서비스 종료에 따른 게시물 백업을 도와드립니다."
    )

    tgd_id = input(
        "트게더 게시판 주소를 입력해 주세요\n예시) https://tgd.kr/s/givemecs 에서 givemecs\n기본값은 미녕이데려오께 트게더입니다.\n>"
    )
    if tgd_id == "":
        tgd_id = "givemecs"

    ## 페이지 테스트용
    # page_number = 332

    page_number = 0
    next = True
    while next:
        page_number = page_number + 1
        print(f"{page_number} 페이지 게시물 URL 모으는 중...")
        article_no_list, next = get_article_no_list(tgd_id, page_number)

        print(f"{page_number} 페이지 게시물 URL 모으기 완료!")
        print(f"{page_number} 페이지 게시물 다운로드 중...")

        for idx, article_no in enumerate(article_no_list):
            print(f"게시물 다운로드 중... {idx + 1} / {len(article_no_list)}")
            download_artice(tgd_id, article_no)

        if next:
            print(f"{page_number} 페이지 게시물 다운로드 완료!")
        else:
            print("모든 게시물 다운로드 완료!")
            break
