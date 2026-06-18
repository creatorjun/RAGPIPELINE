# run.py
import argparse

from src.config import AppConfig
from src.pipeline import PipelineOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 문서 정제 파이프라인")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("--input-dir", help="입력 폴더 (config.yaml 값 오버라이드)")
    parser.add_argument("--output-dir", help="출력 폴더 (config.yaml 값 오버라이드)")
    args = parser.parse_args()

    cfg = AppConfig.from_yaml(args.config)
    if args.input_dir:
        cfg.pipeline.input_dir = args.input_dir
    if args.output_dir:
        cfg.pipeline.output_dir = args.output_dir

    orchestrator = PipelineOrchestrator(cfg)
    orchestrator.run()


if __name__ == "__main__":
    main()
