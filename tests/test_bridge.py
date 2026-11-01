import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _install_stub_modules():
    """Install lightweight stubs for optional external dependencies when running unit tests."""
    if "dotenv" not in sys.modules:
        dotenv_mod = types.ModuleType("dotenv")
        dotenv_mod.load_dotenv = lambda *args, **kwargs: None
        sys.modules["dotenv"] = dotenv_mod

    if "telethon" not in sys.modules:
        telethon_mod = types.ModuleType("telethon")

        class DummyTelegramClient:
            def __init__(self, session, api_id, api_hash):
                if not api_id or not api_hash:
                    raise ValueError("Your API ID or Hash cannot be empty or None.")
                self.session = session
                self.api_id = int(api_id)
                self.api_hash = api_hash

        telethon_mod.TelegramClient = DummyTelegramClient
        sys.modules["telethon"] = telethon_mod

    if "openai" not in sys.modules:
        openai_mod = types.ModuleType("openai")

        class OpenAIError(Exception):
            pass

        class AsyncOpenAI:
            def __init__(self, *args, **kwargs):
                pass

        openai_mod.OpenAIError = OpenAIError
        openai_mod.AsyncOpenAI = AsyncOpenAI
        sys.modules["openai"] = openai_mod

    if "discord" not in sys.modules:
        discord_mod = types.ModuleType("discord")
        app_commands_mod = types.ModuleType("discord.app_commands")

        class DummyIntents:
            guilds = False
            reactions = False

            @classmethod
            def none(cls):
                return cls()

        class DummyCommandTree:
            def __init__(self, client):
                self.client = client

            def command(self, **kwargs):
                def decorator(fn):
                    return fn
                return decorator

        class DummyClient:
            def __init__(self, intents=None):
                self.intents = intents
                self.user = "bot"

            def get_channel(self, channel_id):
                return None

            async def fetch_channel(self, channel_id):
                return None

        app_commands_mod.CommandTree = DummyCommandTree
        app_commands_mod.describe = lambda **kwargs: (lambda fn: fn)
        discord_mod.Client = DummyClient
        discord_mod.Intents = DummyIntents
        discord_mod.Interaction = object
        discord_mod.RawReactionActionEvent = object
        discord_mod.Object = lambda id: types.SimpleNamespace(id=id)
        discord_mod.app_commands = app_commands_mod
        sys.modules["discord"] = discord_mod
        sys.modules["discord.app_commands"] = app_commands_mod

    if "telegram" not in sys.modules:
        tg_mod = types.ModuleType("telegram")
        tg_ext_mod = types.ModuleType("telegram.ext")

        class ReactionTypeEmoji:
            def __init__(self, emoji: str):
                self.emoji = emoji

        class Update:
            ALL_TYPES = "all"

        class DummyApp:
            def __init__(self):
                self.handlers = []
                self.bot = types.SimpleNamespace(
                    username="TariFaqBot",
                    send_message=AsyncMock(),
                )

            def add_handler(self, handler):
                self.handlers.append(handler)

        class ApplicationBuilder:
            def token(self, _token):
                return self

            def build(self):
                return DummyApp()

        class MessageHandler:
            def __init__(self, flt, callback):
                self.filter = flt
                self.callback = callback

        class MessageReactionHandler:
            def __init__(self, callback):
                self.callback = callback

        class _FilterVal:
            def __and__(self, other):
                return self

            def __invert__(self):
                return self

        tg_mod.ReactionTypeEmoji = ReactionTypeEmoji
        tg_mod.Update = Update
        tg_ext_mod.Application = DummyApp
        tg_ext_mod.ApplicationBuilder = ApplicationBuilder
        tg_ext_mod.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
        tg_ext_mod.MessageHandler = MessageHandler
        tg_ext_mod.MessageReactionHandler = MessageReactionHandler
        tg_ext_mod.filters = types.SimpleNamespace(
            ChatType=types.SimpleNamespace(PRIVATE=_FilterVal(), GROUPS=_FilterVal()),
            TEXT=_FilterVal(),
            COMMAND=_FilterVal(),
        )
        sys.modules["telegram"] = tg_mod
        sys.modules["telegram.ext"] = tg_ext_mod

    if "httpx" not in sys.modules:
        httpx_mod = types.ModuleType("httpx")
        httpx_mod.AsyncClient = object
        httpx_mod.HTTPError = Exception
        sys.modules["httpx"] = httpx_mod


_install_stub_modules()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge")))

import discord_handler  # noqa: E402
import faq_archiver  # noqa: E402
import telegram_handler  # noqa: E402
from jobs import customer_analysis_job  # noqa: E402


class DummySender:
    def __init__(self, user_id: int, username: str):
        self.id = user_id
        self.username = username


class DummyMessage:
    def __init__(
        self,
        msg_id: int,
        text: str,
        date: datetime,
        channel_name: str,
        sender: DummySender,
        reply_to_msg_id: int | None = None,
        media: bool = False,
        media_path: str | None = None,
    ):
        self.id = msg_id
        self.text = text
        self.date = date
        self.channel_name = channel_name
        self._sender = sender
        self.reply_to_msg_id = reply_to_msg_id
        self.media = media
        self._media_path = media_path

    async def get_sender(self):
        return self._sender

    async def download_media(self, file=None):
        return self._media_path


class TestFaqArchiver(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        faq_archiver.client = None

    def test_import_and_lazy_client_validation(self):
        with patch.dict(os.environ, {}, clear=True):
            faq_archiver.api_id = None
            faq_archiver.api_hash = None
            faq_archiver.client = None
            with self.assertRaises(ValueError):
                faq_archiver._get_telegram_client()

        with patch.dict(
            os.environ,
            {"TELEGRAM_API_ID": "not_an_int", "TELEGRAM_API_HASH": "abc"},
            clear=True,
        ):
            faq_archiver.api_id = None
            faq_archiver.api_hash = None
            faq_archiver.client = None
            with self.assertRaises(ValueError):
                faq_archiver._get_telegram_client()

        with patch.dict(
            os.environ,
            {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "hash_val"},
            clear=True,
        ):
            faq_archiver.api_id = None
            faq_archiver.api_hash = None
            faq_archiver.client = None
            created = faq_archiver._get_telegram_client()
            self.assertEqual(created.api_id, 12345)
            self.assertEqual(created.api_hash, "hash_val")

    async def test_write_combined_histories_isolate_reply_ids_per_channel(self):
        sender_a = DummySender(1, "alice")
        sender_b = DummySender(2, "bob")
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

        messages = [
            DummyMessage(10, "Channel A root", t0, "chan_a", sender_a),
            DummyMessage(10, "Channel B root", t0, "chan_b", sender_b),
            DummyMessage(11, "Reply in A", t0, "chan_a", sender_b, reply_to_msg_id=10),
            DummyMessage(12, "Reply in B", t0, "chan_b", sender_a, reply_to_msg_id=10),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = os.path.join(tmpdir, "history.txt")
            html_path = os.path.join(tmpdir, "history.html")

            await faq_archiver.write_combined_text_history(
                messages, txt_path, ["chan_a", "chan_b"], 24
            )
            await faq_archiver.write_combined_html_history(
                messages, html_path, ["chan_a", "chan_b<script>"], 24, tmpdir
            )

            with open(txt_path, "r", encoding="utf-8") as f:
                txt = f.read()
            self.assertIn("Message: Reply in A (Replying to: Channel A root)", txt)
            self.assertIn("Message: Reply in B (Replying to: Channel B root)", txt)

            with open(html_path, "r", encoding="utf-8") as f:
                html_out = f.read()
            self.assertIn("Replying to: Channel A root", html_out)
            self.assertIn("Replying to: Channel B root", html_out)
            self.assertIn("chan_b&lt;script&gt;", html_out)
            self.assertNotIn("<script>", html_out)

    async def test_archive_channels_disconnects_client_on_success(self):
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_client.get_messages = AsyncMock(return_value=[])
        faq_archiver.client = mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = os.path.join(tmpdir, "out")
            media_dir = os.path.join(tmpdir, "media")
            stats = await faq_archiver.archive_channels(
                channels=["tariproject"],
                hours_history=1,
                output_dir=out_dir,
                media_folder=media_dir,
                output_as_text=True,
            )
            self.assertEqual(stats["total_messages"], 0)
            mock_client.connect.assert_awaited_once()
            mock_client.disconnect.assert_awaited_once()


class TestCustomerAnalysisJob(unittest.IsolatedAsyncioTestCase):
    async def test_query_openai_analysis_handles_empty_choices_and_none_content(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=types.SimpleNamespace(choices=[])
        )
        with patch.object(customer_analysis_job, "_get_openai_client", return_value=mock_client):
            res = await customer_analysis_job.query_openai_analysis("some chat")
            self.assertIsNone(res)

        empty_msg = types.SimpleNamespace(message=types.SimpleNamespace(content=None))
        mock_client.chat.completions.create = AsyncMock(
            return_value=types.SimpleNamespace(choices=[empty_msg])
        )
        with patch.object(customer_analysis_job, "_get_openai_client", return_value=mock_client):
            res = await customer_analysis_job.query_openai_analysis("some chat")
            self.assertIsNone(res)

    async def test_run_customer_service_analysis_cleans_temp_dir_on_early_return(self):
        async def fake_archive(*args, **kwargs):
            os.makedirs("temp_analysis", exist_ok=True)
            return {"total_messages": 0, "channels_processed": ["tariproject"]}

        bot = MagicMock()
        bot.send_message = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            prev_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "sk-test",
                        "TELEGRAM_API_ID": "12345",
                        "TELEGRAM_API_HASH": "hash",
                    },
                    clear=False,
                ), patch.object(
                    customer_analysis_job, "archive_channels", side_effect=fake_archive
                ):
                    await customer_analysis_job.run_customer_service_analysis(
                        bot, target_group_id="-100123"
                    )
                    self.assertFalse(os.path.exists("temp_analysis"))
            finally:
                os.chdir(prev_cwd)


class TestDiscordAndTelegramHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_discord_reaction_only_confirms_when_kb_push_succeeds(self):
        client = discord_handler.BridgeDiscordClient()
        client.pending_qa[999] = ("How to mine?", "Use Minotari")
        channel = types.SimpleNamespace(send=AsyncMock())
        client.get_channel = MagicMock(return_value=channel)

        payload = types.SimpleNamespace(
            emoji="💾",
            guild_id=1,
            channel_id=2,
            user_id=3,
            message_id=999,
            member=types.SimpleNamespace(roles=[types.SimpleNamespace(id=42)]),
        )

        with patch.dict(os.environ, {"DISCORD_ADMIN_ROLE_ID": "42"}, clear=False):
            with patch.object(discord_handler, "push_to_kb", new=AsyncMock(return_value=False)):
                await client.on_raw_reaction_add(payload)
                channel.send.assert_not_awaited()
                self.assertIn(999, client.pending_qa)

            with patch.object(discord_handler, "push_to_kb", new=AsyncMock(return_value=True)):
                await client.on_raw_reaction_add(payload)
                channel.send.assert_awaited_once_with(
                    "Answer saved to knowledge base (pending review)"
                )
                self.assertNotIn(999, client.pending_qa)

    async def test_telegram_group_mention_case_insensitive_and_kb_reaction(self):
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_ADMIN_IDS": "77"},
            clear=False,
        ):
            app = telegram_handler.build_telegram_app()
            group_handler = app.handlers[1].callback
            reaction_handler = app.handlers[2].callback

            sent_msg = types.SimpleNamespace(message_id=500)
            eff_msg = types.SimpleNamespace(
                text="@TARIFAQBOT how does Tari work?",
                reply_to_message=None,
                reply_text=AsyncMock(return_value=sent_msg),
            )
            update = types.SimpleNamespace(
                effective_message=eff_msg,
                effective_chat=types.SimpleNamespace(id=100),
                effective_user=types.SimpleNamespace(username="tester"),
            )
            ctx = types.SimpleNamespace(bot=app.bot)

            with patch.object(
                telegram_handler,
                "ask_anythingllm",
                new=AsyncMock(return_value="Tari is a privacy protocol"),
            ) as mock_ask:
                await group_handler(update, ctx)
                mock_ask.assert_awaited_once_with("how does Tari work?")

            reaction_update = types.SimpleNamespace(
                message_reaction=types.SimpleNamespace(
                    chat=types.SimpleNamespace(id=100),
                    user=types.SimpleNamespace(id=77),
                    message_id=500,
                    new_reaction=[sys.modules["telegram"].ReactionTypeEmoji("💾")],
                )
            )

            with patch.object(telegram_handler, "push_to_kb", new=AsyncMock(return_value=False)):
                await reaction_handler(reaction_update, ctx)
                app.bot.send_message.assert_not_awaited()

            with patch.object(telegram_handler, "push_to_kb", new=AsyncMock(return_value=True)):
                await reaction_handler(reaction_update, ctx)
                app.bot.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
