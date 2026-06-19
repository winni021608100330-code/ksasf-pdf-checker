from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


BOARD_URL = "https://ksasf.ksa.hs.kr/?action=BD0000M&pagecode=P000000023&language=KR"
TITLE_WORDS = ("본선", "본선진출", "진출팀", "발표")
TARGET_TEXT = (
    "혹등고래 버블넷(Bubble-Net)에서 착안한 나선형 노즐의 회전 상승 흐름을 이용한 "
    "가라앉은 미세플라스틱(PVC) 포집 효과 탐구"
)

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "state.json"
PDF_PATH = ROOT / "data" / "result.pdf"
TIMEOUT = 30


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"processed_posts": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_post(session: requests.Session) -> tuple[str, str]:
    response = session.get(BOARD_URL, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")

    posts: list[tuple[int, str, str]] = []
    for row in soup.select("table tbody tr"):
        link = row.select_one("a[href]")
        number = next((int(text) for text in row.stripped_strings if text.isdigit()), None)
        if link and number is not None and link.get_text(" ", strip=True):
            posts.append((number, link.get_text(" ", strip=True), urljoin(BOARD_URL, link["href"])))

    if posts:
        _, title, url = max(posts, key=lambda post: post[0])
        return title, url

    raise RuntimeError("게시판에서 최신 게시글을 찾지 못했습니다.")


def attached_pdf(session: requests.Session, post_url: str) -> tuple[str, bytes] | None:
    response = session.get(post_url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.select("a[href]"):
        href = link["href"].strip()
        label = unquote(link.get_text(" ", strip=True))
        if ".pdf" not in f"{unquote(href)} {label}".lower():
            continue

        pdf_url = urljoin(post_url, href)
        pdf_response = session.get(pdf_url, headers={"Referer": post_url}, timeout=TIMEOUT)
        pdf_response.raise_for_status()
        if pdf_response.content.startswith(b"%PDF"):
            return pdf_url, pdf_response.content

    return None


def pdf_contains_target(content: bytes) -> bool:
    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    normalized_pdf = "".join(text.split()).casefold()
    normalized_target = "".join(TARGET_TEXT.split()).casefold()
    return normalized_target in normalized_pdf


def send_telegram(title: str, post_url: str, pdf_url: str, content: bytes) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    message = (
        "✅ KSASF 연구 제목 발견\n\n"
        f"게시글: {title}\n"
        f"연구 제목: {TARGET_TEXT}\n"
        f"게시글 URL: {post_url}\n"
        f"PDF URL: {pdf_url}"
    )

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
