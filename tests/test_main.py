import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs

import main as bot
from main import (
    Article,
    ArticleImageParser,
    format_article_message,
    parse_feed,
    process_articles,
    send_to_telegram,
)


class ParseFeedTests(unittest.TestCase):
    def test_reads_article_fields_from_rss(self) -> None:
        xml_data = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <guid>news-1</guid>
            <title>Yangi xabar</title>
            <link>https://kun.uz/news/1</link>
            <category>Jamiyat</category>
            <description><![CDATA[Qisqa maqola tavsifi.]]></description>
            <pubDate>Mon, 16 Nov 2026 18:00:23 +0500</pubDate>
          </item>
        </channel></rss>"""

        self.assertEqual(
            parse_feed(xml_data),
            [
                Article(
                    "news-1",
                    "Yangi xabar",
                    "https://kun.uz/news/1",
                    "Jamiyat",
                    "Qisqa maqola tavsifi.",
                    "Mon, 16 Nov 2026 18:00:23 +0500",
                )
            ],
        )

    def test_rejects_empty_feed(self) -> None:
        with self.assertRaisesRegex(ValueError, "yangiliklar topilmadi"):
            parse_feed(b"<rss><channel /></rss>")


class ProcessArticlesTests(unittest.TestCase):
    def test_first_run_skips_existing_and_later_sends_only_new_articles(self) -> None:
        older = Article("old", "Oldingi xabar", "https://kun.uz/news/old", "")
        latest = Article("new", "Yangi xabar", "https://kun.uz/news/new", "Jahon")
        sent = []

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            send_message = sent.append

            self.assertEqual(process_articles([older], state_path, send_message), 0)
            self.assertEqual(sent, [])
            self.assertEqual(
                process_articles([latest, older], state_path, send_message),
                1,
            )

        self.assertEqual(sent, [latest])


class ArticleImageParserTests(unittest.TestCase):
    def test_reads_open_graph_image(self) -> None:
        parser = ArticleImageParser()
        parser.feed(
            '<html><head><meta content="https://storage.kun.uz/news.jpg" '
            'property="og:image"></head></html>'
        )

        self.assertEqual(parser.image_url, "https://storage.kun.uz/news.jpg")

    def test_uses_twitter_image_when_open_graph_is_missing(self) -> None:
        parser = ArticleImageParser()
        parser.feed(
            '<meta name="twitter:image" content="https://storage.kun.uz/news.jpg">'
        )

        self.assertEqual(parser.image_url, "https://storage.kun.uz/news.jpg")


class FormatArticleMessageTests(unittest.TestCase):
    def test_includes_summary_category_publish_time_and_link(self) -> None:
        article = Article(
            "news-1",
            "Yangi xabar",
            "https://kun.uz/news/1",
            "Jamiyat",
            "Maqolaning qisqa tavsifi.",
            "Mon, 16 Nov 2026 18:00:23 +0500",
        )

        message = format_article_message(article)

        self.assertIn("Maqolaning qisqa tavsifi.", message)
        self.assertIn("Jamiyat", message)
        self.assertIn("Chop etilgan: 16.11.2026 18:00", message)
        self.assertIn("https://kun.uz/news/1", message)

    def test_keeps_photo_caption_within_telegram_limit(self) -> None:
        article = Article(
            "news-1",
            "Yangi xabar",
            "https://kun.uz/news/1",
            "Jamiyat",
            "Tavsif " * 300,
        )

        self.assertLessEqual(len(format_article_message(article)), 1024)


class SendToTelegramTests(unittest.TestCase):
    def test_includes_telegram_error_description_without_exposing_token(self) -> None:
        token = "test-secret-token"
        response_body = b'{"ok":false,"description":"Chat not found"}'
        http_error = HTTPError(
            f"https://api.telegram.org/bot{token}/sendMessage",
            400,
            "Bad Request",
            {},
            io.BytesIO(response_body),
        )
        article = Article("news-1", "Yangi xabar", "https://kun.uz/news/1", "")

        with patch("main.fetch_article_image", return_value=None), patch(
            "main.urlopen", side_effect=http_error
        ):
            with self.assertRaisesRegex(RuntimeError, "Chat not found") as error:
                send_to_telegram(token, "@wrong_channel", article)

        self.assertNotIn(token, str(error.exception))

    def test_sends_photo_with_caption_when_article_image_exists(self) -> None:
        response = io.BytesIO(b'{"ok":true}')
        article = Article(
            "news-1",
            "Yangi xabar",
            "https://kun.uz/news/1",
            "Jamiyat",
            "Maqolaning qisqa tavsifi.",
            "Mon, 16 Nov 2026 18:00:23 +0500",
        )

        with patch(
            "main.fetch_article_image",
            return_value="https://storage.kun.uz/news.jpg",
        ), patch("main.urlopen", return_value=response) as urlopen_mock:
            send_to_telegram("test-token", "@channel", article)

        request = urlopen_mock.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/sendPhoto"))
        payload = parse_qs(request.data.decode("utf-8"))
        self.assertEqual(payload["photo"], ["https://storage.kun.uz/news.jpg"])
        self.assertIn("Yangi xabar", payload["caption"][0])
        self.assertIn("Maqolaning qisqa tavsifi.", payload["caption"][0])
        self.assertIn("Jamiyat", payload["caption"][0])
        self.assertIn("16.11.2026 18:00", payload["caption"][0])


class MainTests(unittest.TestCase):
    def test_ctrl_c_logs_normal_shutdown_without_traceback(self) -> None:
        article = Article("news-1", "Yangi xabar", "https://kun.uz/news/1", "")

        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHANNEL_ID": "@channel",
                "STATE_FILE": str(Path(directory) / "state.json"),
            }
            with patch.dict(os.environ, environment), patch(
                "main.fetch_articles", return_value=[article]
            ), patch("main.time.sleep", side_effect=KeyboardInterrupt):
                with self.assertLogs(level="INFO") as captured:
                    bot.main()

        output = "\n".join(captured.output)
        self.assertIn("Bot to‘xtatildi.", output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
