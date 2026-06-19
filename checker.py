from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


BOARD_URL = "https://ksasf.ksa.hs.kr/?action=BD0000M&pagecode=P000000023&language=KR"
POST_KEYWORDS = ("본선", "본선진출", "진출팀", "발표")
SEARCH_TEXT = "버블넷"
STATE_FILE = Path(__file__).resolve().parent / "data" / "state.json"
TIMEOUT = 30


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"processed_pdfs": {}}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    return {"processed_pdfs": state.get("processed_pdfs", {})}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get(session: requests.Session, url: str, referer: str | None = None) -> requests.Response:
    headers = {"Referer": referer} if referer else None
    response = session.get(url, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def latest_post(session: requests.Session) -> tuple[str, str]:
    response = get(session, BOARD_URL)
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    posts: list[tuple[int, str, str]] = []

    for row in soup.select("table tbody tr"):
        link = row.select_one("a[href]")
        number = next((int(value) for value in row.stripped_strings if value.isdigit()), None)
        if link and number is not None:
            title = link.get_text(" ", strip=True)
            if title:
                posts.append((number, title, urljoin(BOARD_URL, link["href"])))

    if not posts:
        raise RuntimeError("최신 게시글을 찾지 못했습니다.")

    _, title, post_url = max(posts, key=lambda item: item[0])
    return title, post_url


def attached_pdf_urls(session: requests.Session, post_url: str) -> list[str]:
    response = get(session, post_url)
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    urls: list[str] = []

    for link in soup.select("a[href]"):
        href = link["href"].strip()
        label = link.get_text(" ", strip=True)
        if ".pdf" in unquote(f"{href} {label}").lower():
            pdf_url = urljoin(post_url, href)
            if pdf_url not in urls:
                urls.append(pdf_url)

    return urls


def extract_text(pdf: bytes) -> str:
    reader = PdfReader(BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def send_telegram(title: str, post_url: str, pdf_url: str, found: bool) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    result = "발견됨" if found else "발견되지 않음"
    message = (
        "KSASF PDF 검색 결과\n\n"
        f"게시글: {title}\n"
        f"검색어: {SEARCH_TEXT}\n"
        f"결과: {result}\n"
        f"게시글 URL: {post_url}\n"
        f"PDF URL: {pdf_url}"
    )

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=TIMEOUT,
    ).raise_for_status()


def main() -> None:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; KSASF-PDF-Checker/1.0)"
    state = load_state()
    processed = state["processed_pdfs"]

    title, post_url = latest_post(session)
    print(f"게시글 발견: {title}")

    if not any(keyword in title for keyword in POST_KEYWORDS):
        return

    for pdf_url in attached_pdf_urls(session, post_url):
        print(f"첨부 PDF 발견: {pdf_url}")
        response = get(session, pdf_url, post_url)
        pdf = response.content
        if not pdf.startswith(b"%PDF"):
            continue

        sha256 = hashlib.sha256(pdf).hexdigest()
        if processed.get(pdf_url) == sha256 or sha256 in processed.values():
            processed[pdf_url] = sha256
            continue

        print(f"PDF 변경 감지: {sha256}")
        found = SEARCH_TEXT.casefold() in extract_text(pdf).casefold()
        print(f"연구 제목 발견: {'예' if found else '아니오'}")

        send_telegram(title, post_url, pdf_url, found)
        print("Telegram 전송 완료: 성공")
        processed[pdf_url] = sha256

    save_state(state)


if __name__ == "__main__":
    main()
