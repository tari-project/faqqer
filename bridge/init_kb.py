import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from kb_queue import push_to_kb


logger = logging.getLogger(__name__)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    env_path = Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logger.info("Loaded env file: %s", env_path)
    else:
        load_dotenv()
        logger.warning("No bridge/.env found; relying on process environment")

    repo_root = Path(__file__).resolve().parent.parent
    faqs_dir = repo_root / "faqs"
    if not faqs_dir.exists():
        logger.error("FAQs directory not found: %s", faqs_dir)
        return 1

    uploaded = 0
    failed = 0

    for path in sorted(faqs_dir.glob("*.txt")):
        if path.name == "faq_l2_general.txt":
            logger.info("Skipping %s (explicitly excluded)", path.name)
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            failed += 1
            logger.error("Failed to read %s: %s", path.name, e)
            continue

        ok = await push_to_kb(question=path.stem, answer=content)
        if ok:
            uploaded += 1
            logger.info("Uploaded %s (ok)", path.name)
        else:
            failed += 1
            logger.error("Uploaded %s (failed)", path.name)

    print(f"{uploaded} files uploaded, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

