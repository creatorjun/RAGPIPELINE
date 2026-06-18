# search.py
import argparse

from src.config import AppConfig
from src.rag.engine import RagEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 검색 및 답변 생성")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("question", help="질의 내용")
    parser.add_argument(
        "--domain",
        nargs="+",
        help="도메인 필터 (build maintenance incident 중 1개 이상)",
    )
    parser.add_argument(
        "--no-answer",
        action="store_true",
        help="LLM 응답 없이 검색 결과만 출력",
    )
    args = parser.parse_args()

    cfg = AppConfig.from_yaml(args.config)
    engine = RagEngine(cfg)
    result = engine.query(args.question, domain_filter=args.domain)

    print("\n" + "=" * 60)
    print(f"  질문: {result.question}")
    print("=" * 60)

    print("\n[검색 된 참조 문서]")
    for r in result.sources:
        print(f"  [{r.rank + 1}] (score={r.score:.4f}) {r.chunk.section_title}")
        print(f"       파일: {r.chunk.source_file}  도메인: {r.chunk.domain}")

    if not args.no_answer:
        print("\n[답변]")
        print(result.answer)
    print()


if __name__ == "__main__":
    main()
