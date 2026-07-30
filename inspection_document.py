[Data Service] Inspection Document 변환 (Korean)
목적

Data Agent가 inspection result document를 안정적으로 활용할 수 있도록 document 변환 pipeline 구축
LLM이 조회하기 쉬운 형태의 summary collection 생성

현재 상태

데이터 서비스는 수집된 inspection result document를 MongoDB("inspections" collection)에 저장 중
Inspection data는 Object Storage에 저장 중
하나의 document에 하나 이상의 검사 모델 결과가 포함됨
Data count에 따라 document 길이가 매우 길어질 수 있음

문제점

Data Agent가 현재 document를 그대로 사용 시 두 가지 이슈 존재

"inspectionResults" field가 nested 구조 → LLM 성능에 따라 올바른 query 작성 실패 가능
일부 document가 매우 큼 → MCP 서버로 조회 시 LLM의 context window 초과로 crash 발생



Solution

각 inspection document에서 필요한 정보만 추출하여 별도 MongoDB collection에 저장
변환 단위: (inspection document × 검사 모델) 당 summary document 1개 생성

Nested 구조 제거, flat한 구조로 저장 → LLM query 작성 용이
Document 크기가 data count와 무관하게 일정 수준으로 bounded



추출 정보

Metadata: gbm, process, location, equipmentId, productId, createdAt, localTimezone, mode, inspectionDataPath
원본 참조: inspectionDocId (원본 document의 _id) → 필요 시 원본 drill-down 가능
모델 정보: modelName, modelVersion, task, classes, threshold
판정 정보: conclusion (제품 단위), modelDecision (해당 모델 단위)
Result Summary:

dataCount: totalCount 및 class별 count
confidenceScore: class별 average/minimum/maximum (+ 가중 평균 계산용 sum)
elapsedTime: average/minimum/maximum (+ sum)


Sample Results:

Class별 sample inspection result 저장
NG는 cap(예: 20개) 이내 전체 저장, OK는 소수 sample만 저장
Sample은 필요 field만 저장 (predictionId, inferenceStartedAt, elapsedTime, prediction, confidence, decision, data 참조)


운영 정보: uploadStatus, uploadedAt

활용 방안

검사 환경 monitoring: 기간별 평균 confidence score/inference time, NG rate 등 조회
성능 저하 감지: 모델별 confidence 추세 분석 (예: 2주간 지속 하락 감지)
검사 결과 조회: productId 기반 제품 단위 조회, NG 발생 prediction 확인
Feature vector operation 연계: sample의 data 참조를 통해 Milvus 유사도 검색/sampling으로 연결

고려 사항

Summary 생성 시점: Data Service 수집 시점 생성 vs batch 생성 → 결정 필요
기존 document backfill 전략 필요
Aggregation 성능 확보를 위한 index 구성 필요 (예: {equipmentId, modelName, createdAt})
Sample의 data 참조가 Object Storage/Milvus vector와 연결 가능해야 함 (Category D use case의 전제 조건)


[Data Service] Inspection Document Conversion (English)
Purpose

Build a document conversion pipeline so the Data Agent can use inspection result documents reliably
Create a summary collection in a form that is easy for the LLM to query

Current State

Data Service saves collected inspection result documents in MongoDB ("inspections" collection)
Inspection data is saved in Object Storage
One document can contain results of one or more inspection models
Depending on data count, a document can get very long

Problems

Two main issues if the Data Agent uses the current documents as-is

"inspectionResults" field is nested → depending on LLM performance, LLM may fail to write correct queries
Some documents are very large → LLM crashes due to context window overflow when retrieving via MCP server



Solution

Extract only necessary information from each inspection document and save it to a separate MongoDB collection
Conversion unit: one summary document per (inspection document × inspection model)

Nested structure removed, stored in flat form → easier LLM query writing
Document size bounded regardless of data count



Extracted Information

Metadata: gbm, process, location, equipmentId, productId, createdAt, localTimezone, mode, inspectionDataPath
Source reference: inspectionDocId (_id of the original document) → enables drill-down to the original when needed
Model info: modelName, modelVersion, task, classes, threshold
Decision info: conclusion (unit level), modelDecision (this model's level)
Result Summary:

dataCount: totalCount and per-class count
confidenceScore: per-class average/minimum/maximum (+ sum for weighted average computation)
elapsedTime: average/minimum/maximum (+ sum)


Sample Results:

Store sample inspection results per class
NG: store all up to a cap (e.g., 20); OK: store only a few samples
Samples keep only necessary fields (predictionId, inferenceStartedAt, elapsedTime, prediction, confidence, decision, data reference)


Operational info: uploadStatus, uploadedAt

Usage

Inspection environment monitoring: query average confidence score/inference time, NG rate, etc. by period
Performance degradation detection: per-model confidence trend analysis (e.g., detect consistent decline over 2 weeks)
Inspection result retrieval: unit-level lookup by productId, identify NG-triggering predictions
Link to feature vector operations: connect to Milvus similarity search/sampling via sample data references

Considerations

Summary generation timing: on-ingest by Data Service vs. batch → decision needed
Backfill strategy needed for existing documents
Index configuration needed for aggregation performance (e.g., {equipmentId, modelName, createdAt})
Sample data references must be resolvable to Object Storage/Milvus vectors (prerequisite for Category D use cases)




{
  "_id": "68be85a0381b40e1fc8f4c6e",
  "inspectionDocId": "6a35de4ca439075d85f9b4e0",   // 원본 inspection document _id (drill-down용)

  "gbm": "SEHC",
  "process": "Side",
  "location": "VM07",
  "equipmentId": "SEHC_Side_VM07",
  "productId": "12HJ3NGL601105Z",
  "createdAt": "2026-06-20T00:26:10.374+00:00",
  "localTimezone": "Asia/Bangkok",
  "mode": "production",
  "inspectionDataPath": "E:\\COSMO\\DataStorage\\SEHC\\Side\\20260620\\002630658631",

  "modelName": "sidetopsideu8000",
  "modelVersion": "sidetopsideu8000_260316_260316081905",
  "task": "cls",
  "classes": ["OK", "NG"],
  "threshold": 0.5,

  "conclusion": "OK",           // 제품 단위 최종 판정
  "modelDecision": "OK",        // 해당 모델의 판정

  "resultSummary": {
    "dataCount": { "totalCount": 100, "OK": 80, "NG": 20 },
    "confidence": {             // class별 통계, sum은 가중 평균 계산용
      "OK": { "avg": 0.97, "min": 0.62, "max": 1.0, "sum": 77.6 },
      "NG": { "avg": 0.91, "min": 0.55, "max": 0.99, "sum": 18.2 }
    },
    "confidenceHistogram": {    // 0.1 단위 10개 bucket (optional)
      "OK": [0, 0, 0, 0, 0, 1, 2, 5, 22, 50],
      "NG": [0, 0, 0, 0, 0, 2, 3, 4, 6, 5]
    },
    "elapsedTime": { "avg": 0.2, "min": 0.1, "max": 0.3, "sum": 20.0 },
    "borderlineCount": 3        // threshold ± band 내 prediction 수
  },

  "samples": {
    "OK": [                     // OK는 소수 sample만 저장
      {
        "predictionId": 0,
        "inferenceStartedAt": "2026-06-20T00:26:05.408+00:00",
        "elapsedTime": 0.2,
        "prediction": "OK",
        "decision": "OK",
        "confidence": 0.88,
        "dataRef": "SEHC_Side_VM07/20260620/002630658631/0"   // Object Storage/Milvus 연결용 참조
      }
    ],
    "NG": [                     // NG는 cap(예: 20개) 이내 전체 저장
      {
        "predictionId": 3,
        "inferenceStartedAt": "2026-06-20T00:26:05.421+00:00",
        "elapsedTime": 0.2,
        "prediction": "NG",
        "decision": "NG",
        "confidence": 0.97,
        "dataRef": "SEHC_Side_VM07/20260620/002630658631/3"
      }
    ],
    "borderline": [             // threshold ± band 내 prediction, cap 적용
      {
        "predictionId": 7,
        "inferenceStartedAt": "2026-06-20T00:26:05.430+00:00",
        "elapsedTime": 0.2,
        "prediction": "OK",
        "decision": "OK",
        "confidence": 0.55,
        "dataRef": "SEHC_Side_VM07/20260620/002630658631/7"
      }
    ]
  },
  "ngTruncated": false,         // NG가 cap 초과로 잘렸는지 여부

  "uploadStatus": "completed",
  "uploadedAt": "2026-06-20T05:07:25.639+00:00"
}
