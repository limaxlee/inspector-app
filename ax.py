진행 현황
W31

Data Agent 활용 방안 구성: 사용자-agent 간 use case 시나리오 도출

예: 검사 환경 monitoring 및 성능 저하 감지 — 평균 confidence score가 2주간 지속 하락 시 agent가 분석 후 자연어로 제공
MongoDB의 Inspection/Model document 기반 monitoring 검토


Document 조회 검토 결과:

Model document는 크기가 작아 조회 문제 없음 → 현재 바로 사용 가능
Inspection document는 data count에 따라 매우 길어짐 → LLM 조회 시 crash 발생
→ 필요 정보를 추출하여 별도 collection에 저장 필요 (MongoDB MCP 서버가 해당 collection 사용)


Inspection document 변환 방안 제안 (상세: Inspection Document 변환 페이지 참조):

(inspection document × 검사 모델) 당 flat한 summary document 1개 생성
통계(class별 confidence/elapsedTime avg·min·max), class별 sample, 원본 참조(inspectionDocId), data 참조(dataRef) 포함
변환 기능은 Data Service의 background worker로 구현 예정
※ 현재 제안 단계이며 변경 가능




[AX Task] Data Agent Development — Confluence Page (Completed, English)
Background

Expansion of the DICE platform is increasing data volume and deepening analysis bottlenecks
Data analysis difficulties for non-developers and field personnel
Inspection environment monitoring/analysis difficulties even for developers
→ Need for natural-language-based data/inspection analysis

Goal

Development of an AI Agent for natural-language-based data and inspection result analysis
Provide natural-language-based data analysis and visualization
Transition to conversational analysis and automated reporting

Scope

Provide data and inspection result analysis functions:

Inspection environment monitoring: check inspection environment by model (or process/equipment) for a given period (average confidence score, average inference time, etc.)
Similar data search: feature-vector-based similarity search
Training data selection: coreset sampling for retraining



Plan
MilestoneDetailsTargetStatusM1. Use case definition & agent architectureDefine use case scenarios (monitoring/similarity search/data selection); finalize Root Orchestrator + specialist agent (mongodb_scanner, milvus_scanner) structureW31DoneM2. DA Backend — Session DBPer-user conversation session/history and event history management, PostgreSQLW30Done (deployed on server 173)M3. DA Backend — Artifact ServiceStore/manage data uploaded to the agent (images etc.) in Object Storage; workflow validated with demo versionW33In progressM4. MongoDB MCP Server — core toolsetCore MongoDB access tools implemented and deployed on server 173 (port 8444)W30DoneM5. MongoDB MCP Server — dedicated retrieval toolsImplement 2 dedicated tools for model/inspection document retrieval (removes LLM query-writing failure risk vs. generic find tool)W33PlannedM6. Inspection document conversionFinalize summary schema → implement conversion pipeline as Data Service background worker → backfill existing documents → configure indexesW34Planned (schema proposed)M7. Milvus MCP Server — similarity searchSimilarity search and other toolsets implemented, deployed on server 173 (port 8443)W30DoneM8. Milvus MCP Server — data samplingImplement coreset sampling tool (classification/detection support; detection details on GitHub Wiki)W34In progressM9. Feature vector extraction pipelineBuild vector extraction pipeline on Suwon server using trained inspection models (workaround for Edge extraction/transfer constraint); store vectors with scalar metadata in Milvus collectionsW35PlannedM10. Agent integrationIntegrate Root Orchestrator + specialist agents on Fabrix ADK; select and validate tool-calling-capable Gauss modelW36PlannedM11. Use case integration testingEnd-to-end tests per UC (monitoring/model retrieval/inspection retrieval/similarity search/sampling) and response quality validationW37PlannedM12. Demo & initial releaseInternal demo, feedback collection, initial version releaseW38PlannedM13. Extension — composite scenarios & auto reportingMulti-UC chained workflows (e.g., degradation detection→analysis→retraining data prep), periodic automated reportingW40~Planned
Progress
W31

Constructed possible ways the Data Agent can be used: derived user–agent use case scenarios

Example: inspection environment monitoring and degradation detection — if average confidence score consistently declines over 2 weeks, the agent analyzes it and reports in natural language
Reviewed monitoring based on Inspection/Model documents in MongoDB


Document retrieval review results:

Model documents are short → retrievable without issue, ready to use now
Inspection documents can get very long depending on data count → LLM crashes on retrieval
→ Necessary information must be extracted and saved to a separate collection (used by the MongoDB MCP server)


Proposed inspection document conversion (details: see Inspection Document Conversion page):

One flat summary document per (inspection document × inspection model)
Includes statistics (per-class confidence/elapsedTime avg·min·max), per-class samples, source reference (inspectionDocId), data reference (dataRef)
Conversion to be implemented as a background worker in Data Service
※ Proposal stage — subject to change
