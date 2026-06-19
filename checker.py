from __future__ import annotations

import json
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


BOARD_URL = "https://ksasf.ksa.hs.kr/?action=BD0000M&pagecode=P000000023&language=KR"
POST_KEYWORDS = ("본선", "본선진출", "진출팀", "발표")
TARGET_TITLE = (
    "혹등고래 버블넷(Bubble-Net)에서 착안한 나선형 노즐의 회전 상승 흐름을 이용한 "
    "가라앉은 미세플라스틱(PVC) 포집 효과 탐구"
)

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "state.json"
PDF_FILE = ROOT / "data" / "matched.pdf"
TIMEOUT = 30


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"processed_posts": []}
    return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def find_latest_target_post(session: requests.Session) -> tuple[str, str] | None:
    soup = BeautifulSoup(get_html(session, BOARD_URL), "html.parser")
    candidates: list[tuple[int, str, str]] = []

    for row in soup.select("table tbody tr"):
        link = row.select_one("a[href]")
        number = next((int(value) for value in row.stripped_strings if value.isdigit()), None)
        if not link or number is None:
            continue

        title = link.get_text(" ", strip=True)
        years = [int(year) for year in re.findall(r"20\d{2}", row.get_text(" ", strip=True))]
        is_current = not years or max(years) >= datetime.now().year
        if is_current and title and any(keyword in title for keyword in POST_KEYWORDS):
            candidates.append((number, title, urljoin(BOARD_URL, link["href"])))

    if not candidates:
        return None

    _, title, post_url = max(candidates, key=lambda item: item[0])
    return title, post_url


def find_attached_pdfs(session: requests.Session, post_url: str) -> list[str]:
    soup = BeautifulSoup(get_html(session, post_url), "html.parser")
    pdf_urls: list[str] = []

    for link in soup.select("a[href]"):
        href = link["href"].strip()
        label = link.get_text(" ", strip=True)
        if ".pdf" in unquote(f"{href} {label}").lower():
            pdf_url = urljoin(post_url, href)
            if pdf_url not in pdf_urls:
                pdf_urls.append(pdf_url)

    return pdf_urls


def download_pdf(session: requests.Session, pdf_url: str, post_url: str) -> bytes | None:
    response = session.get(pdf_url, headers={"Referer": post_url}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.content if response.content.startswith(b"%PDF") else None


def contains_target_title(pdf: bytes) -> bool:
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    normalized_text = "".join(text.split()).casefold()
    normalized_target = "".join(TARGET_TITLE.split()).casefold()
    return normalized_target in normalized_text


def send_telegram(title: str, post_url: str, pdf_url: str, pdf: bytes) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    message = (
        "✅ KSASF 연구 제목 발견\n\n"
        f"게시글: {title}\n"
        f"연구 제목: {TARGET_TITLE}\n"
        f"게시글 URL: {post_url}\n"
        f"PDF URL: {pdf_url}"
    )

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=TIMEOUT,
    ).raise_for_status()

    PDF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PDF_FILE.write_bytes(pdf)
    with PDF_FILE.open("rb") as file:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": title},
            files={"document": ("ksasf-result.pdf", file, "application/pdf")},
            timeout=60,
        ).raise_for_status()


def main() -> None:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; KSASF-PDF-Checker/1.0)"
    state = load_state()
    processed = set(state.get("processed_posts", []))

    post = find_latest_target_post(session)
    if not post:
        print("조건에 맞는 게시글이 없습니다.")
        return

    title, post_url = post
    if post_url in processed:
        print("이미 처리한 게시글입니다.")
        return

    print(f"처리 대상 게시글: {title}")
    for pdf_url in find_attached_pdfs(session, post_url):
        pdf = download_pdf(session, pdf_url, post_url)
        if pdf and contains_target_title(pdf):
            send_telegram(title, post_url, pdf_url, pdf)
            print("연구 제목 발견: Telegram 전송 완료")
            break
    else:
        print("연구 제목을 찾지 못해 전송하지 않았습니다.")

    processed.add(post_url)
    state["processed_posts"] = sorted(processed)
    save_state(state)


if __name__ == "__main__":
    main()
