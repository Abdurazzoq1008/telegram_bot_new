import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


RSS_URL = "https://kun.uz/news/rss?lang=uz"
USER_AGENT = "KunUzTelegramBot/1.0"
MAX_SAVED_IDS = 2000
MAX_CAPTION_LENGTH = 1024


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    link: str
    category: str
    description: str = ""
    published_at: str = ""


class ArticleImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta" or self.image_url:
            return

        metadata = dict(attrs)
        image_property = metadata.get("property", "").lower()
        image_name = metadata.get("name", "").lower()
        if image_property == "og:image" or image_name == "twitter:image":
            self.image_url = metadata.get("content")


def parse_feed(xml_data: bytes) -> list[Article]:
    root = ET.fromstring(xml_data)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Kun.uz RSS lentasida channel topilmadi")

    articles = []
    for item in channel.findall("item"):
        article_id = (item.findtext("guid") or item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        category = (item.findtext("category") or "").strip()
        description = (item.findtext("description") or "").strip()
        published_at = (item.findtext("pubDate") or "").strip()
        if not article_id or not title or not link:
            raise ValueError("Kun.uz RSS lentasida ID, sarlavha yoki havola yo‘q")
        articles.append(
            Article(article_id, title, link, category, description, published_at)
        )
    if not articles:
        raise ValueError("Kun.uz RSS lentasida yangiliklar topilmadi")
    return articles


def format_published_at(published_at: str) -> str:
    try:
        published = parsedate_to_datetime(published_at)
    except (TypeError, ValueError, OverflowError):
        return published_at
    return published.strftime("%d.%m.%Y %H:%M")


def format_article_message(article: Article) -> str:
    metadata = []
    if article.category:
        metadata.append(article.category)
    if article.published_at:
        metadata.append(f"Chop etilgan: {format_published_at(article.published_at)}")

    source = f"Batafsil: {article.link}"
    suffix_parts = [" | ".join(metadata)] if metadata else []
    suffix_parts.append(source)
    title = article.title

    title_budget = MAX_CAPTION_LENGTH - len("\n\n".join(suffix_parts)) - 2
    if len(title) > title_budget:
        title = title[: max(0, title_budget - 1)].rstrip() + "…"

    fixed_parts = [title, *suffix_parts]
    fixed_message = "\n\n".join(fixed_parts)
    description = article.description.strip()
    if not description:
        return fixed_message

    description_budget = MAX_CAPTION_LENGTH - len(fixed_message) - 4
    if description_budget <= 0:
        return fixed_message
    if len(description) > description_budget:
        description = description[: description_budget - 1].rstrip() + "…"

    return "\n\n".join([title, description, *suffix_parts])


def fetch_articles() -> list[Article]:
    request = Request(RSS_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            return parse_feed(response.read())
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Kun.uz RSS lentasini olishda xato: {error}") from error


def fetch_article_image(article_url: str) -> str | None:
    request = Request(article_url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            html_data = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as error:
        logging.warning("Maqola sahifasini olishda xato; rasm yuborilmaydi: %s", error)
        return None

    parser = ArticleImageParser()
    parser.feed(html_data)
    if not parser.image_url:
        logging.warning("Maqolada rasm topilmadi: %s", article_url)
    return parser.image_url


def load_seen_ids(path: Path) -> set[str] | None:
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("seen_ids"), list):
        raise ValueError(f"{path} faylining formati noto‘g‘ri")
    if not all(isinstance(item_id, str) for item_id in data["seen_ids"]):
        raise ValueError(f"{path} ichidagi seen_ids qiymatlari noto‘g‘ri")
    return set(data["seen_ids"])


def save_seen_ids(path: Path, seen_ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    saved_ids = sorted(seen_ids)[-MAX_SAVED_IDS:]
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps({"seen_ids": saved_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def send_to_telegram(token: str, channel_id: str, article: Article) -> None:
    message = format_article_message(article)

    image_url = fetch_article_image(article.link)
    payload_data = {"chat_id": channel_id}
    method = "sendMessage"
    if image_url:
        method = "sendPhoto"
        payload_data.update({"photo": image_url, "caption": message})
    else:
        payload_data.update({"text": message, "disable_web_page_preview": "true"})

    payload = urlencode(payload_data).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            response_body = error.read().decode("utf-8", errors="replace")
        finally:
            error.close()
        try:
            response_data = json.loads(response_body)
        except json.JSONDecodeError:
            response_data = {}
        description = response_data.get("description", response_body[:500])
        raise RuntimeError(
            f"Telegram API xatosi (HTTP {error.code}): {description}"
        ) from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Telegramga xabar yuborishda xato: {error}") from error

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API xatosi: {result.get('description', result)}")


def process_articles(
    articles: list[Article],
    state_path: Path,
    send_message: Callable[[Article], None],
) -> int:
    seen_ids = load_seen_ids(state_path)
    if seen_ids is None:
        save_seen_ids(state_path, {article.id for article in articles})
        logging.info(
            "Boshlang‘ich holat saqlandi; eski xabarlar yuborilmadi (%d ta).",
            len(articles),
        )
        return 0

    new_articles = [article for article in articles if article.id not in seen_ids]
    sent_count = 0
    for article in reversed(new_articles):
        send_message(article)
        seen_ids.add(article.id)
        save_seen_ids(state_path, seen_ids)
        logging.info("Yuborildi: %s", article.title)
        sent_count += 1
    return sent_count


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not channel_id:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN va TELEGRAM_CHANNEL_ID muhit o‘zgaruvchilarini kiriting."
        )

    try:
        poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
    except ValueError as error:
        raise SystemExit("POLL_INTERVAL_SECONDS butun son bo‘lishi kerak.") from error
    if poll_interval < 10:
        raise SystemExit("POLL_INTERVAL_SECONDS kamida 10 soniya bo‘lishi kerak.")

    state_path = Path(os.environ.get("STATE_FILE", "seen_articles.json"))
    send_message = lambda article: send_to_telegram(token, channel_id, article)
    logging.info("Kun.uz yangiliklari tekshirilmoqda (har %d soniyada).", poll_interval)

    try:
        while True:
            try:
                process_articles(fetch_articles(), state_path, send_message)
            except (RuntimeError, ValueError, ET.ParseError, OSError):
                logging.exception("Tekshirish/yuborish amalga oshmadi.")
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logging.info("Bot to‘xtatildi.")


if __name__ == "__main__":
    main()
