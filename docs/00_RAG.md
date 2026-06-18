# RAG (Retrieval-Augmented Generation) 검증 방법론 총람

RAG는 LLM의 지식 격리 문제를 해결하는 핵심 패러다임으로, 2025~2026년에 걸쳐 아키텍처별로 다수의 검증된 방법론이 정립되었습니다.

---

## 1. 검색(Retrieval) 최적화 방법론

### 쿼리 최적화

- **HyDE (Hypothetical Document Embeddings):** 실제 문서 대신 가상의 답변 문서를 생성하여 임베딩 공간에서 검색 정밀도를 높이는 기법
- **Multi-Query / Sub-Query:** 단일 쿼리를 여러 시각의 쿼리로 분해하여 재조합, 재현율(Recall)을 향상시킴
- **Step-Back Prompting:** 구체 질문을 더 추상적인 상위 질문으로 변환 후 검색하여 맥락 이해도 향상
- **Chain-of-Verification:** 쿼리 확장 후 검색 결과를 단계적으로 검증하는 기법

### 임베딩 모델

- **BGE, Voyage, AngIE** 등 고성능 Dense 임베딩 모델이 기존 BM25 기반 Sparse 검색 대비 우수한 의미 검색 정확도를 달성
- **ColBERT, DPR (Dense Passage Retrieval):** End-to-End 학습을 통해 Retriever-Generator 공동 최적화

### Hybrid Retrieval & Re-ranking

- **RRF (Reciprocal Rank Fusion):** Sparse(BM25)와 Dense 벡터 검색 결과를 순위 기반으로 융합, 단일 방식보다 일관되게 높은 성능
- **LLM 기반 List-wise / Adaptive Re-ranking:** BERT, Cohere Rerank, BGE-Reranker-Large 등을 사용하여 검색 결과를 재순위화, MRR@5 기준 최대 59% 절대값 향상
- **HNSW-IP-Fusion-minilm:** 벡터 인덱스 기법과 Fusion을 결합, Coverage Retrieval 0.942 / Faithfulness 0.970 달성

---

## 2. 청킹(Chunking) & 인덱싱 방법론

### Decoupled Chunking (Search/Retrieve 분리)

전통적인 고정 크기 청킹의 "정밀도 vs 완전성" 트레이드오프를 해결하기 위해,
**검색용 소형 청크**와 **생성용 대형 청크**를 분리하는 방식이 검증됨

### TreeRAG (계층적 트리 구조)

오프라인에서 LLM을 사용해 문서를 계층적 트리 요약 구조로 변환하고, 온라인
검색 시 소형 청크로 위치를 파악한 뒤 인접 노드들을 동적으로 조합하여 완전한
컨텍스트를 조립하는 방식

### GraphRAG (지식 그래프 기반)

문서에서 엔티티와 관계를 추출하여 지식 그래프를 구성, 물리적으로 멀리 떨어진
정보 간의 연결 관계를 그래프 순회(Personalized PageRank 등)로 탐색 —
다양성(Diversity) 지표에서 62% 이상 우위 달성

### RAPTOR (재귀적 요약 트리)

계층적 요약 트리를 구성하고 각 레벨에서 검색, GPT-4 기준 QuALITY 벤치마크에서
정확도 20% 향상

---

## 3. 적응형(Adaptive) & 동적(Dynamic) RAG

| 방법론 | 핵심 메커니즘 | 검증 성과 |
|---|---|---|
| **Self-RAG** | "Reflection Token"을 생성해 검색 여부를 자체 판단, Fragment 수준 Beam Search | Open-domain QA 및 추론에서 기존 RAG 대비 팩트 정확도 ~80% 향상 |
| **FLARE** | 생성 중 신뢰도가 임계치 이하로 떨어지면 실시간 검색 트리거 | 적응형 검색으로 불필요한 검색 비용 절감 |
| **Dynamic RAG** | LLM의 생성 과정에서 언제/무엇을 검색할지 동적으로 결정 | SIGIR 2025 튜토리얼로 채택될 만큼 핵심 연구 방향으로 부상 |
| **Parametric RAG** | 검색된 지식을 입력 레벨이 아닌 파라미터 레벨로 주입 | 효율성과 효과성 모두 향상 |

---

## 4. Multi-hop & 복합 추론 RAG

- **RT-RAG (Reasoning Tree Guided RAG, 2026):** 멀티홉 질문을 명시적인 Reasoning Tree로 분해, Bottom-Up 순회 전략으로 증거 수집 — SOTA 대비 F1 +7.0%, EM +6.0% 달성
- **ITER-RETGEN:** 검색-생성을 반복(Iterative)하여 서로의 결과가 상대를 강화하는 피드백 루프 구축
- **IRCoT / ToC:** Chain-of-Thought와 반복 검색을 결합한 재귀적 쿼리 정제
- **CoopRAG (NeurIPS 2025):** Retriever의 초기/후기 레이어와 LLM이 지식을 교환하며 협력하는 Co-operative RAG 프레임워크

---

## 5. Agentic RAG

멀티스텝 추론, 도구 사용, 반성(Reflection)과 결합하여 RAG 프로세스 자체를
에이전트가 제어하는 패러다임으로, 2025년 기준 가장 빠르게 성장하는 영역

- **Tool Retrieval:** 수백~수천 개의 MCP 도구 설명을 벡터/하이브리드 인덱스로 관리하고, 현재 태스크에 맞는 Top-k 도구만 동적으로 컨텍스트에 삽입 — BM25만으로도 강력한 베이스라인 성능 달성
- **Context Engineering:** RAG + Memory + Tool Retrieval을 통합하여 LLM에 최적 컨텍스트를 동적 조립하는 상위 아키텍처 패러다임

---

## 6. 멀티모달 RAG

- **Native Multimodal Path:** 이미지를 직접 토크나이징하여 텍스트 토큰과 통합된 멀티모달 인코더에 함께 입력, 퓨즈드 멀티벡터 표현 생성
- **Text-First, Tensor Reranking:** PDF에서 파싱된 텍스트로 초기 Full-text + 단일 벡터 인덱스 구축 후, 전체 페이지를 이미지로 변환한 텐서 표현으로 정교한 Re-ranking 수행
- **RULE:** 의료 Vision-Language Model을 위한 멀티모달 RAG, 의학 팩트 정확도 향상 검증

---

## 7. 도메인 특화 RAG

- **RAFT (Retrieval-Augmented Fine-Tuning):** 학습 시 방해 문서(Distractor)를 함께 노출시켜 모델이 관련 없는 문서를 무시하도록 훈련 — PubMed, HotpotQA 등에서 검증
- **HyPA-RAG:** 법률/정책 도메인에 특화된 하이브리드 적응형 RAG
- **Radiology RAG:** 도메인 특화 벡터 DB(3,689개 RadioGraphics 논문) 구축 시, GPT-4 시험 점수 75.5% → 81.2% 향상, 관련 참고문헌 87.5% 정확 인용

---

## 8. 평가 프레임워크

- **RAGAS:** Context Relevance, Answer Faithfulness, Answer Relevance 3가지 핵심 지표로 RAG 전체 파이프라인 평가
- **RAGCHECKER:** RAG 컴포넌트별 세부 오류 분석 도구
- **MIRAGE / RGB / RECALL:** Multi-hop 및 도메인 특화 RAG 평가용 벤치마크 데이터셋
- **XRAG:** 검색 유닛 매칭(Conventional Retrieval), 토큰 매칭(Conventional Generation), 시맨틱 이해(Cognitive LLM) 3가지 관점의 통합 평가 벤치마크
- **CRUMQs (2025):** 답변 불가 쿼리와 실제 멀티홉 추론이 필요한 쿼리를 자동 생성하여 RAG 시스템의 한계를 진단, 기존 벤치마크 대비 Cheatability 81% 감소

---

## 아키텍처 분류 요약

1. **Retriever-centric:** 검색 품질 최적화가 핵심 (Hybrid Retrieval, Re-ranking, HyDE 등)
2. **Generator-centric:** 생성 제어 및 신뢰성 강화 (Self-RAG, Decoding Control 등)
3. **Hybrid:** 검색-생성 공동 최적화 (ITER-RETGEN, CoopRAG 등)
4. **Robustness-oriented:** 노이즈 및 적대적 입력 대응 (RAFT, CRUMQs 등)