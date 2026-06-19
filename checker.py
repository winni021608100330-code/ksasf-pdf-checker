TARGET_POST_KEYWORDS = [
    "본선",
    "본선진출",
    "진출팀",
    "발표"
]
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DOWNLOAD_DIR = DATA_DIR / "pdfs"
STATE_PATH = DATA_DIR / "processed_pdfs.json"

KSASF_PAGE_URL = (
    "https://ksasf.ksa.hs.kr/"
    "?action=BD0000M&pagecode=P000000023&language=KR"
)
KEYWORDS = ["혹등고래 버블넷", "버블넷", "Bubble-Net"]

REQUEST_TIMEOUT = 40
MAX_DETAIL_PAGES = 30
USER_AGENT = "ksasf-pdf-checker/1.0 (GitHub Actions)"


@dataclass(frozen=True)
class PdfLink:
    url: str
    title: str


def now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def session() -> requests.Session:
    client = requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})
    return client


def fetch_page(client: requests.Session, url: str) -> str:
    response = client.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def looks_like_pdf(href: str, text: str) -> bool:
    combined = unquote(f"{href} {text}").lower()
    return ".pdf" in combined or "pdf 다운로드" in combined or "pdf download" in combined


def same_site(url: str, base_url: str) -> bool:
    return urlparse(url).netloc == urlparse(base_url).netloc


def links_from_html(html: str, page_url: str) -> tuple[list[PdfLink], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    pdf_links: list[PdfLink] = []
    detail_links: list[str] = []
    def is_target_post(title: str) -> bool:
    return any(keyword in title for keyword in TARGET_POST_KEYWORDS)

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue

        absolute_url = urljoin(page_url, href)
        text = " ".join(anchor.stripped_strings).strip()
        title = text or Path(unquote(urlparse(absolute_url).path)).name or "KSASF PDF"

        if looks_like_pdf(href, text):
            pdf_links.append(PdfLink(absolute_url, title))
        elif same_site(absolute_url, page_url):
            detail_links.append(absolute_url)

    return pdf_links, detail_links


def discover_pdf_links(client: requests.Session, start_url: str) -> list[PdfLink]:

    html = fetch_page(client, start_url)

    soup = BeautifulSoup(html, "html.parser")

    pdf_links: list[PdfLink] = []

    for anchor in soup.select("a[href]"):

        text = " ".join(anchor.stripped_strings).strip()

        if not is_target_post(text):
            continue

        detail_url = urljoin(start_url, anchor.get("href"))

        print(f"Target post found: {text}")

        try:
            detail_html = fetch_page(client, detail_url)
        except Exception:
            continue

        detail_soup = BeautifulSoup(detail_html, "html.parser")

        for pdf_anchor in detail_soup.select("a[href]"):

            href = pdf_anchor.get("href", "")

            if "download.php" in href.lower() or ".pdf" in href.lower():

                pdf_url = urljoin(detail_url, href)

                pdf_links.append(
                    PdfLink(
                        pdf_url,
                        text
                    )
                )

    return pdf_links

def download_pdf(client: requests.Session, link: PdfLink) -> tuple[bytes, str]:
    response = client.get(link.url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    content = response.content

    content_type = response.headers.get("Content-Type", "").lower()
    if not content.startswith(b"%PDF") and "application/pdf" not in content_type:
        raise ValueError(f"The discovered link did not return a PDF: {link.url}")

    return content, hashlib.sha256(content).hexdigest()


def safe_pdf_filename(link: PdfLink, digest: str) -> str:
    url_name = Path(unquote(urlparse(link.url).path)).name
    base_name = url_name if url_name.lower().endswith(".pdf") else f"{link.title}.pdf"
    stem = Path(base_name).stem
    clean_stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", stem).strip("_") or "ksasf"
    return f"{clean_stem}_{digest[:12]}.pdf"


def extract_pdf_text(content: bytes) -> tuple[str, int]:
    reader = PdfReader(BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages), len(reader.pages)


def find_keywords(text: str) -> list[str]:
    lowered = text.casefold()
    return [keyword for keyword in KEYWORDS if keyword.casefold() in lowered]


def telegram_credentials() -> tuple[str, str]:
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
    )


def send_telegram_message(message: str) -> None:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        print("Telegram secrets are missing. Notification skipped.")
        return

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message, "disable_web_page_preview": False},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def send_telegram_pdf(path: Path, caption: str) -> None:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        return

    with path.open("rb") as pdf_file:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"document": (path.name, pdf_file, "application/pdf")},
            timeout=90,
        )
    response.raise_for_status()


def result_message(link: PdfLink, matched: list[str], page_count: int) -> str:
    result = "검색 키워드 발견" if matched else "검색 키워드 없음"
    keyword_text = ", ".join(matched) if matched else "없음"
    return (
        "📄 KSASF 새 PDF 감지\n\n"
        f"제목: {link.title}\n"
        f"시간: {now_text()}\n"
        f"페이지 수: {page_count}\n"
        f"결과: {result}\n"
        f"발견 키워드: {keyword_text}\n"
        f"PDF: {link.url}"
    )


def process_pdf(
    client: requests.Session,
    link: PdfLink,
    processed: dict[str, dict[str, str]],
) -> bool:
    content, digest = download_pdf(client, link)
    previous = processed.get(link.url, {})
    if previous.get("sha256") == digest:
        print(f"Already processed: {link.url}")
        return False

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = DOWNLOAD_DIR / safe_pdf_filename(link, digest)
    pdf_path.write_bytes(content)

    text, page_count = extract_pdf_text(content)
    matched = find_keywords(text)

if matched:
    message = (
        "🎉 KSASF 본선 진출팀 PDF에서 연구 제목 발견!\n\n"
        f"제목: {link.title}\n"
        f"시간: {now_text()}\n"
        f"페이지 수: {page_count}\n"
        f"발견 키워드: {', '.join(matched)}\n"
        f"PDF: {link.url}"
    )

    send_telegram_message(message)

    send_telegram_pdf(
        pdf_path,
        f"🎉 연구 제목 발견! {', '.join(matched)}"
    )

    print(f"FOUND: {matched}")

else:
    print(f"SKIP: {link.title}")

    processed[link.url] = {
        "sha256": digest,
        "title": link.title,
        "checked_at": now_text(),
        "matched_keywords": ", ".join(matched),
        "local_file": str(pdf_path.relative_to(PROJECT_DIR)),
    }
    print(f"Processed new PDF: {link.title}; matched={matched}")
    return True


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    processed = load_json(STATE_PATH, {})
    client = session()

    print(f"KSASF PDF Checker started: {now_text()}")
    pdf_links = discover_pdf_links(client, KSASF_PAGE_URL)
    print(f"Discovered PDF links: {len(pdf_links)}")

    new_count = 0
    for link in pdf_links:
        try:
            if process_pdf(client, link, processed):
                new_count += 1
        except Exception as exc:
            print(f"ERROR processing {link.url}: {exc}")
            send_telegram_message(
                "⚠️ KSASF PDF Checker 오류\n\n"
                f"제목: {link.title}\n"
                f"오류: {exc}\n"
                f"URL: {link.url}"
            )

    save_json(STATE_PATH, processed)
    print(f"Finished. New or updated PDFs: {new_count}")


if __name__ == "__main__":
    main()
