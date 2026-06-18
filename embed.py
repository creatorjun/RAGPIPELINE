# embed.py
import argparse

from src.config import AppConfig
from src.rag.indexer import RagIndexer


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 임베딩 인덱싱 실행")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    args = parser.parse_args()

    cfg = AppConfig.from_yaml(args.config)
    indexer = RagIndexer(cfg)
    indexer.run()


if __name__ == "__main__":
    main()
