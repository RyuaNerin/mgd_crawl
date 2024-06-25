from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
from selenium_stealth import stealth
import pyautogui, pyperclip
import os.path
import sys

def write_info(article_info):
    filename = url_id + "_info.txt"
    if os.path.isfile(filename):
        with open(filename, "a") as file:
            file.write(article_info + "\n")
    else:
        with open(filename, "w") as file:
            file.write("번호 | 일시 | 카테고리 | 제목 | 글쓴이\n")
            file.write(article_info + "\n")

def check_duplicate(url_number):
    ## 중복이면 True, 중복이 아니면 False
    filename = url_id + "_info.txt"
    if os.path.isfile(filename):
        with open(filename, 'r') as file:
            if str(url_number) in file.read():
                return True
            else:
                return False
    else:
        return False

def get_href_list(page_number):
    url = tgd_url + "/s/" + url_id + "/page/" + str(page_number)
    driver = webdriver.Chrome(options=options, service=ChromeService(ChromeDriverManager().install()))
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )

    driver.get(url)
    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, 'html.parser')

    article_href_list = []

    for i in soup.find_all('div', class_='list-title'):
        article_href_list.append(i.find('a')["href"])

    # print(article_href_list)
    # print(soup.find('a', {"rel": "next"}))

    ## 다음 페이지 있으면 True, 다음 페이지 없으면 False
    if soup.find('a', {"rel": "next"}) == None:
        return {'article_href_list': article_href_list, 'is_next': False}
    else:
        return {'article_href_list': article_href_list, 'is_next': True}

    

def download_artice(article_href):
    url_number = article_href.replace("/s/" + url_id + "/", "")
    if check_duplicate(url_number):
        return
    
    article_url = tgd_url + article_href
    print(article_url)
    driver = webdriver.Chrome(options=options, service=ChromeService(ChromeDriverManager().install()))
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )

    driver.get(article_url)

    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    article_info = url_number + " | "

    try:
        article_time = soup.select_one("span#article-time > span").text
    except:
        return
    article_info = article_info + article_time + " | "

    article_head = soup.select_one("div#article-info > h2").text.split("\n")
    if len(article_head) == 2:
        title = article_head[1].strip()
        article_info = article_info + title + " | "
    else:
        category = article_head[1].strip()
        article_info = article_info + category + " | "
        title = article_head[2].strip()
        article_info = article_info + title + " | "

    writer = soup.select_one("div#article-info-writer > strong").text
    article_info = article_info + writer

    print(article_info)
    #write_info(article_info)

    if sys.platform == 'darwin':
        ## 맥 환경
        time.sleep(1)
        pyautogui.hotkey('command', 's')
        time.sleep(1)
        pyperclip.copy(url_number)
        time.sleep(1)
        pyautogui.hotkey("command", "v")
        time.sleep(1)
        pyautogui.hotkey('command', 's')
        time.sleep(10)
    else:
        pyautogui.hotkey('ctrl', 's')
        time.sleep(1)
        pyperclip.copy(url_number)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.hotkey('enter')
        time.sleep(10)
    

print("안녕하세요, 미게더 크롤러입니다. 트게더 서비스 종료에 따른 게시물 백업을 도와드립니다.")
url_id = input("트게더 게시판 주소를 입력해 주세요\n예시) https://tgd.kr/s/givemecs 에서 givemecs\n기본값은 미녕이데려오께 트게더입니다.\n>")

if url_id == "":
    url_id = "givemecs"

tgd_url = "https://tgd.kr"

options = webdriver.ChromeOptions()
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

## 페이지 테스트용
# page_number = 332

page_number = 0
while True:
    page_number = page_number + 1
    print(str(page_number) + "페이지 게시물 URL 모으는 중...")
    href_list = get_href_list(page_number)

    print(str(page_number) + "페이지 게시물 URL 모으기 완료!")
    print(str(page_number) + "페이지 게시물 다운로드 중...")
    for article_href in href_list['article_href_list']:
        download_artice(article_href)

    if href_list['is_next']:
        print(str(page_number) + "페이지 게시물 다운로드 완료!")
    else:
        print("모든 게시물 다운로드 완료!")
        break
