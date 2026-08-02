# [AX][공통] Data Agent 개발 — 추진 계획 (Milestone 세부 내용)

## 1. 데이터 에이전트 구조 설계

- 역할별 책임을 명확히 분리하기 위해 modular multi-agent 구조로 설계
  - **Root Orchestrator**: 사용자의 자연어 요청 해석, specialist agent 관리, task delegation 및 전체 workflow orchestration 담당
  - **Specialist Agents**: 각 agent가 단일 도메인 담당
    - mongodb_scanner (MongoDB Agent): 법인에 배포된 모델 정보 및 검사 결과 summary 조회
    - milvus_scanner (Milvus Agent): 유사도 검색, coreset sampling 등 feature vector 관련 operation 수행
  - **MCP Servers**: agent에 DB 접근 권한 및 tool 제공 (MongoDB MCP 서버, Milvus MCP 서버)
- Agent Framework: Fabrix ADK 사용
  - Google ADK 기능 대부분을 wrapping하면서 사내 Gauss 모델 접근 기능 추가 제공
  - Constraint: tool calling을 지원하는 모델이 제한적 → tool calling 및 image input을 지원하는 Gemma4로 모델 선정 (W30)
- 구현 상태: 구조 설계 완료

## 2. [PoC] 유사 데이터 탐색

- 목적: 데이터의 feature vector 기반 유사 데이터 검색 기능의 실현 가능성 검증
- Feature 추출 모델 검토:
  - 학습된 검사 모델로 직접 추출이 어려운 경우를 고려하여 pretrained 모델 (DINOv2/v3 등) 활용 검토
  - 검토 결과: pretrained 모델은 general 특징만 capture하여 성능 미흡 → 학습된 검사 모델이 추출하는 feature vector 사용으로 결정
- PoC 진행 (Epoxy 과제 대상):
  - Classification task: 이미지 feature 추출 → 데이터 중복 제거 및 유사도 검색 검증 완료
  - Detection task: PoC 진행 중 (Global Feature, Bounding Box Feature 2종 handling 필요)
- 구현 상태: classification 검증 완료, detection 진행 중

## 3. [PoC] 학습 데이터 선별

- 목적: 데이터들의 feature vector를 이용한 coreset (stratified) sampling으로 (재)학습용 데이터 선별 검증 → labeling/학습 비용 절감
- 지원 범위: classification 및 detection task만 지원 예정
  - Detection 데이터는 classification 대비 sampling이 tricky한 상태 (Global Feature / Bounding Box Feature handling 필요)
  - Sampling 상세 내용은 GitHub Wiki 페이지에 작성 예정
- 구현 상태: classification 대상 sampling 구현 진행 중

## 4. [Data Service] 검사 결과 Document 변환

- 배경: Data Agent가 현재 inspection document를 그대로 사용 시 두 가지 이슈 발생
  - "inspectionResults" field가 nested 구조 → LLM 성능에 따라 올바른 query 작성 실패 가능
  - 일부 document가 매우 큼 (data count에 비례) → MCP 서버로 조회 시 LLM context window 초과로 crash 발생
- Solution: 각 inspection document에서 필요 정보만 추출하여 flat한 구조의 summary document를 별도 collection에 저장
  - 변환 단위: (inspection document × 검사 모델) 당 summary document 1개 생성
  - 추출 정보: metadata, 원본 document reference, 모델 정보, 판정 정보 (conclusion), 검사 결과 summary (data count/confidence/elapsed time 통계), class별 sample 검사 결과
  - 상세 내용: [데이터 서비스] 검사 결과 Document Conversion 페이지 참조
- 구현 방안: on-ingest 및 on-demand 방식 기반으로 구현
  - Data Service가 실행하고 있는 통계 정보 caching 기능과 동일하게 구현
  - 백그라운드 worker 및 API Endpoint 정의 (API Endpoint는 기존 document backfill 시 필요)
- 구현 상태: schema 설계 완료, 변환 pipeline 구현 예정

## 5. [MongoDB MCP] 핵심 Toolset 구현

MongoDB 접근 core tool 구현:

- database 조회
- collection 조회
- collection 생성
- collection 삭제
- collection 이름 변경
- database 통계 정보 조회
- collection 통계 정보 조회
- collection의 index 목록 조회
- collection의 index 생성
- collection의 index 삭제
- 서버 status 조회
- database ping
- one (or many) document 생성
- document 검색
- document aggregate
- document 업데이트
- document 삭제
- [ new ] 모델 정보 조회
- [ new ] 검사 결과 조회

일반 tool: 17개, Data Service specific tool: 2개

- Data Service specific tool이 필요한 원인:
  - 검사 결과나 모델 정보는 일반 document 검색 tool로도 조회 가능
  - 발생 이슈: 언어 모델 (특히 성능이 average인 모델)이 document 검색 tool 사용 시 검색 query를 잘못 작성하는 경우가 있음
  - 솔루션: 검사 결과 및 모델 정보 조회 전용 tool 구현
  - Note. '검사 결과 조회' tool은 검사 결과 summary document의 신규 schema 확정 후 구현 가능 (Milestone 4 선행 필요)
- 구현 상태: 핵심 toolset 구현 완료, 173 서버에 구축 완료 (port 8444)

## 6. [Milvus MCP] 핵심 Toolset 구현

Milvus DB 접근 core tool 구현:

- database 조회
- collection 조회
- collection 정보 조회
- collection 생성
- collection 로드
- collection 삭제
- collection에 데이터 insert
- collection에 vector 검색
- collection 데이터 검색
- coreset (stratified) sampling
- [ new ] OS에서 데이터 retrieve 및 collection에 vector 검색
- [ new ] coreset sampling 및 sampled된 데이터 zip 파일 OS 업로드

일반 tool: 9개, Special tool: 2개

- Special tool이 필요한 원인:
  - Data Agent의 Artifact Service가 Object Storage (OS) 기반으로 구현됨 → 데이터 (이미지 등) 전달 및 반환은 OS를 경유하는 workflow가 최적
  - 데이터 유사도 검색 workflow:
    1. 사용자가 이미지를 Data Agent에 업로드
    2. Agent가 이미지를 OS에 업로드하고 object key 획득
    3. Agent가 MCP tool 호출 시 해당 key를 전달
    4. MCP 서버가 OS에서 실제 이미지를 retrieve → feature 추출 → vector 검색 수행
    5. MCP 서버는 유사 이미지를 직접 반환하는 대신, 각 이미지에 대한 presigned URL을 생성하여 반환
    6. 사용자는 presigned URL을 통해 이미지를 직접 다운로드
  - Coreset sampling workflow:
    1. Sampling tool 호출 시 MCP 서버가 coreset sampling 수행
    2. Sampled 데이터가 다수인 경우 이미지별 presigned URL 반환은 비효율적 → MCP 서버가 OS에서 각 데이터를 retrieve하여 zip 파일 생성 후 OS에 업로드
    3. zip 파일의 presigned URL을 반환 → 사용자는 zip 파일을 직접 다운로드
  - Note. Artifact 전달/반환 방안을 여러 방식으로 검토한 결과 상기 workflow가 가장 적합한 것으로 판단, 데이터 유사도 검색 workflow는 동작 검증 완료
- 구현 상태: 유사도 검색 및 기타 toolset 구현 완료, 데이터 sampling 구현 중, 173 서버에 구축 완료 (port 8443)

## 7. [Data Agent] Backend - Session Service 구현

- LLM의 Database 기반 Session 서비스 구현
  - User별 대화 session/history 및 event history 관리 및 저장
  - Session 생성/조회/삭제 등 기능 구현
- In-Memory Session 서비스 대비 설정은 복잡하지만 production 환경에서 더 stable → Database Session 서비스 선택
- PostgreSQL 사용: 173 서버, port 5432에 구축 완료
- Session title 생성 등 부가 task 처리를 위한 별도 internal agent 정의 (최소 규모의 Gauss 모델 적용)

## 8. [Data Agent] Backend - Artifact Service 구현

- LLM의 Object Storage 기반 Artifact 서비스 구현
  - Agent에 업로드되는 데이터 (이미지 등) OS에 저장 및 관리
  - MCP 서버와의 artifact 전달/반환 workflow의 기반 (Milestone 6 참조)
- 구현 상태: demo 버전으로 workflow 검증 완료

## 9. [Data Agent] Frontend 구현

- 자연어 기반 대화형 UI 구현
  - 대화 session 목록 조회/생성/삭제 (Session Service 연동)
  - 이미지 등 데이터 업로드 기능 (Artifact Service 연동, 유사도 검색 시 필요)
  - 검사 현황/모델 성능 등 조회 결과 표시 및 presigned URL 기반 결과 데이터 (유사 이미지, sampled zip 파일) 다운로드 지원
- 구현 상태: 착수 예정

## 10. [Data Service] Feature vector 추출 Pipeline

- 배경: 데이터의 feature vector quality가 데이터 sampling 및 유사도 검색 성능에 직접적으로 영향
  - 학습된 검사 모델이 추출하는 feature vector 사용 결정 (Milestone 2 검토 결과 참조)
  - Constraint: Edge에서 feature vector를 추출하여 데이터와 함께 수원 서버로 전송하기 어려운 상태 → 수원 서버에 vector 추출 pipeline 구축 필요
- 구현 방안:
  - 수원 서버에 수집된 데이터에 대해 학습된 검사 모델 기반 feature vector 추출
  - 추출된 vector를 Milvus Vector DB collection에 저장 → Milvus MCP 서버의 유사도 검색 및 coreset sampling에 활용
- 구현 상태: 착수 예정
