[Data Service] Data Agent Use Case 시나리오 (Korean)
목적

Data Agent가 사용자에게 제공하는 핵심 use case 정의
초기 버전은 소수의 의미 있는 기능에 집중, 이후 단계적 확장

전제

자연어 요청은 Root Orchestrator가 해석 후 specialist agent(mongodb_scanner, milvus_scanner)에 위임
MongoDB 조회는 inspection summary collection 및 model collection 기반 (원본 inspections collection 직접 조회 없음)
Feature vector operation은 Milvus MCP 서버 기반 (유사도 검색 구현 완료, data sampling 구현 중)
Data sampling은 classification/detection task만 지원 예정


UC-1. 검사 환경 Monitoring
UC-1a. 검사 현황 조회 (기간별)

목적: 사용자가 법인/공정/설비/모델 단위로 검사 환경 현황 확인
요청 예시:

"지난 7일간 SEHC Side 공정 검사 현황 보여줘"
"지난주 VM07의 sidebottom 모델 평균 confidence와 inference time 알려줘"


동작: mongodb_scanner가 summary collection을 기간/scope 조건으로 aggregation
출력: 검사 수, class별 count 및 NG rate, 모델별 평균/최소/최대 confidence, 평균 inference time

UC-1b. 성능 저하 감지 (추세 분석)

목적: 모델 성능 또는 검사 환경의 점진적 저하를 사전 감지
요청 예시:

"sidetopsideu8000 모델의 confidence가 최근 2주간 하락 추세인지 확인해줘"
"VM07의 이번 주 NG rate를 지난주와 비교해줘"


동작: mongodb_scanner가 일 단위 aggregation → Orchestrator가 추세 분석 후 자연어로 해석 제공
출력: 추세 판정(안정/저하/개선) + 근거 수치 + 자연어 해석 (예: 원인 후보 및 권장 조치)

UC-2. 배포 모델 정보 조회

목적: 법인에 배포된 모델의 이름/버전/task/배포 날짜 등 metadata 확인
요청 예시:

"SEHC Side 공정에 배포된 모델 목록 보여줘"
"sideinsideu8000의 현재 버전과 배포 날짜 알려줘"


동작: mongodb_scanner가 model collection 조회
출력: 모델 inventory (이름/버전/task/설비/배포 날짜) 또는 개별 질의 응답
비고: model document는 크기가 작아 제약 없이 바로 조회 가능

UC-3. 검사 결과 조회

목적: 특정 제품 또는 조건에 해당하는 검사 결과 확인
요청 예시:

"productId 12HJ3NGL601105Z의 검사 결과 보여줘"
"오늘 VM07에서 NG 판정된 제품 목록과 NG 발생 prediction 보여줘"


동작: mongodb_scanner가 summary collection을 productId/설비/기간/판정 조건으로 조회
출력: 제품 단위 검사 요약, NG 발생 모델 및 prediction 정보 (samples.NG 활용)
비고: 상세 원본 확인 필요 시 inspectionDocId로 drill-down 가능

UC-4. 데이터 유사도 검색

목적: 기준 데이터와 유사한 데이터를 축적 데이터에서 탐색
요청 예시:

"이 NG 데이터와 유사한 데이터 50개 찾아줘"
"6월 18일 발견된 신규 불량과 유사한 과거 데이터 찾아줘"


동작:

mongodb_scanner가 기준 데이터의 검사 record 및 dataRef 확인
milvus_scanner가 해당 모델 collection에서 top-K 유사도 검색 수행
검색 결과를 검사 정보(제품/설비/날짜/판정)와 매핑하여 제공


출력: 유사도 순위 목록 + 검사 context + 데이터 참조
활용 가치: 불량 유출 분석, 신규 불량 유형에 대한 dataset 신속 구축

UC-5. 학습 데이터 선별 (Data Sampling)

목적: 재학습용 데이터를 대표성/다양성 기준으로 선별하여 labeling/학습 비용 절감
요청 예시:

"지난달 VM07 데이터에서 sidebottom 재학습용 대표 데이터 1,000개 선별해줘"
"이번 주 수집된 OK 데이터 중 다양성 있는 5% 선별해줘"


동작:

mongodb_scanner가 후보 pool 조건(모델/설비/기간/class) 확인
milvus_scanner가 feature vector 기반 sampling 수행


출력: 선별 데이터 목록(ID + 데이터 참조) + 선별 요약(pool 크기, 선별 수)
비고:

Milvus MCP 서버의 data sampling 구현 완료 후 제공
Classification/detection task만 지원 예정 (detection sampling 상세는 GitHub Wiki 참조)



복합 시나리오 (확장)

단일 자연어 요청으로 여러 use case 연계 수행
예시: "sidebottom confidence가 2주간 하락 중인데, 분석하고 재학습 데이터 준비해줘"

UC-1b (추세 확인) → UC-3 (NG/borderline 데이터 확인) → UC-5 (sampling) → 분석 report + 재학습 데이터 목록 출력


초기 버전 이후 단계적 지원 예정

제약 및 고려 사항

Inspection summary collection 구축이 UC-1, UC-3의 전제 조건
dataRef ↔ Object Storage ↔ Milvus vector 연결 규약 표준화가 UC-4, UC-5의 전제 조건
Milvus vector에 scalar metadata(equipmentId, model, date, decision) 필요 → UC-5의 후보 pool을 filter로 정의하기 위함
LLM tool calling 제약 (Fabrix ADK 제공 Gauss 모델 중 일부만 지원) → 복잡한 복합 시나리오는 모델 성능 검증 후 확장


[Data Service] Data Agent Use Case Scenarios (English)
Purpose

Define the core use cases the Data Agent provides to users
Initial version focuses on a few meaningful functions, with staged expansion afterward

Assumptions

Natural language requests are interpreted by the Root Orchestrator and delegated to specialist agents (mongodb_scanner, milvus_scanner)
MongoDB queries are based on the inspection summary collection and model collection (no direct queries on the raw inspections collection)
Feature vector operations are based on the Milvus MCP server (similarity search implemented, data sampling in progress)
Data sampling will support classification/detection tasks only


UC-1. Inspection Environment Monitoring
UC-1a. Inspection Status Check (Period-Based)

Goal: User checks inspection environment status by GBM/process/equipment/model
Example requests:

"Show me the inspection status of SEHC Side process for the last 7 days"
"What was the average confidence and inference time of sidebottom on VM07 last week?"


Operation: mongodb_scanner aggregates the summary collection by period/scope conditions
Output: Inspection count, per-class counts and NG rate, per-model avg/min/max confidence, average inference time

UC-1b. Performance Degradation Detection (Trend Analysis)

Goal: Detect gradual degradation of model performance or inspection environment in advance
Example requests:

"Check if confidence of sidetopsideu8000 has been declining over the past 2 weeks"
"Compare this week's NG rate of VM07 with last week"


Operation: mongodb_scanner performs daily aggregation → Orchestrator analyzes trend and provides natural language interpretation
Output: Trend verdict (stable/degrading/improving) + supporting numbers + natural language interpretation (e.g., candidate causes and recommended actions)

UC-2. Deployed Model Information Retrieval

Goal: Check metadata of models deployed at sites — name/version/task/deployment date
Example requests:

"List the models deployed on SEHC Side process"
"What is the current version and deployment date of sideinsideu8000?"


Operation: mongodb_scanner queries the model collection
Output: Model inventory (name/version/task/equipment/deployment date) or individual answers
Note: Model documents are small, so they can be queried directly without constraints

UC-3. Inspection Result Retrieval

Goal: Check inspection results for a specific product or condition
Example requests:

"Show me the inspection result of productId 12HJ3NGL601105Z"
"List NG products on VM07 today with the NG-triggering predictions"


Operation: mongodb_scanner queries the summary collection by productId/equipment/period/decision
Output: Unit-level inspection summary, NG model and prediction info (using samples.NG)
Note: Drill-down to the original document is possible via inspectionDocId when details are needed

UC-4. Data Similarity Search

Goal: Search accumulated data for data similar to a reference sample
Example requests:

"Find 50 data samples similar to this NG data"
"Find past data similar to the new defect found on June 18"


Operation:

mongodb_scanner locates the reference sample's inspection record and dataRef
milvus_scanner performs top-K similarity search on the corresponding model collection
Search results are mapped with inspection info (product/equipment/date/decision)


Output: Similarity-ranked list + inspection context + data references
Value: Defect escape analysis, rapid dataset construction for new defect types

UC-5. Training Data Selection (Data Sampling)

Goal: Select retraining data by representativeness/diversity to reduce labeling/training cost
Example requests:

"Select 1,000 representative samples from last month's VM07 data for retraining sidebottom"
"Select a diverse 5% subset from this week's OK data"


Operation:

mongodb_scanner determines candidate pool conditions (model/equipment/period/class)
milvus_scanner performs feature-vector-based sampling


Output: Selected data list (IDs + data references) + selection summary (pool size, selected count)
Notes:

Available after data sampling implementation in the Milvus MCP server is complete
Classification/detection tasks only (detection sampling details in GitHub Wiki)



Composite Scenarios (Extension)

Chain multiple use cases from a single natural language request
Example: "Confidence of sidebottom has been declining for 2 weeks — analyze it and prepare retraining data"

UC-1b (trend confirmation) → UC-3 (NG/borderline data check) → UC-5 (sampling) → output: analysis report + retraining data list


To be supported in stages after the initial version

Constraints and Considerations

Inspection summary collection is a prerequisite for UC-1 and UC-3
Standardized dataRef ↔ Object Storage ↔ Milvus vector linkage convention is a prerequisite for UC-4 and UC-5
Milvus vectors require scalar metadata (equipmentId, model, date, decision) → needed to define UC-5 candidate pools as filters
LLM tool calling constraint (only some Gauss models in Fabrix ADK support it) → complex composite scenarios to be expanded after model performance validation
