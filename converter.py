#!/usr/bin/env python3
"""
migrate_inspection_docs.py

Reads inspection documents from a SOURCE MongoDB collection (one document per
inspection event, containing multiple AI models each with a raw list of
per-image predictions) and writes them, reshaped, into a DESTINATION MongoDB
collection (one document PER AI MODEL, with the predictions collapsed into a
resultSummary + a small sample of OK/NG predictions).

Install deps:
    pip install pymongo --break-system-packages

Configure the CONFIG block below (or override via environment variables /
CLI args -- see bottom of file) and run:

    python migrate_inspection_docs.py
    python migrate_inspection_docs.py --dry-run                       # print, don't write
    python migrate_inspection_docs.py --limit 100                      # test on 100 docs

Only pulls documents matching filters (never the whole collection):

    # createdAt range (metadata.createdAt), inclusive start / exclusive end
    python migrate_inspection_docs.py --start-date 2026-06-20 --end-date 2026-06-21

    # only specific AI model(s) (matches inspectionResult.aiResults.aiModel)
    python migrate_inspection_docs.py --ai-model sidetopsideu8000 --ai-model sidebottom

    # exact aiModel string match instead of "modelName part" match
    python migrate_inspection_docs.py --ai-model sidetopsideu8000/sidetopsideu8000_260316_260316081905 --ai-model-exact

    # combine both
    python migrate_inspection_docs.py --start-date 2026-06-20 --end-date 2026-06-21 --ai-model sidetopsideu8000
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError

# --------------------------------------------------------------------------
# CONFIG -- edit these, or set the equivalent env vars, or pass CLI flags.
# --------------------------------------------------------------------------

SRC_URI        = os.environ.get("SRC_MONGO_URI", "mongodb://SRC_HOST:27017")
SRC_DB         = os.environ.get("SRC_MONGO_DB", "source_db")
SRC_COLLECTION = os.environ.get("SRC_MONGO_COLLECTION", "inspection_raw")

DST_URI        = os.environ.get("DST_MONGO_URI", "mongodb://DST_HOST:27017")
DST_DB         = os.environ.get("DST_MONGO_DB", "dest_db")
DST_COLLECTION = os.environ.get("DST_MONGO_COLLECTION", "inspection_summary")

# How many sample predictions to keep per class (OK / NG) in the output doc.
SAMPLE_SIZE = int(os.environ.get("SAMPLE_SIZE", "3"))

# Which sample predictions to keep: "first" (in predictionId/list order) or
# "highest" (highest confidence first).
SAMPLE_STRATEGY = os.environ.get("SAMPLE_STRATEGY", "first")  # "first" | "highest"

# How to compute the "confidence" of a single prediction for the summary
# stats. Default = confidence of the predicted class (max of the vector).
# Alternative: confidence[0] if you specifically want the OK-class score
# regardless of which class was predicted -- change CONFIDENCE_MODE below.
CONFIDENCE_MODE = os.environ.get("CONFIDENCE_MODE", "predicted_class")  # "predicted_class" | "class0"

BATCH_SIZE = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Transformation logic
# --------------------------------------------------------------------------

def prediction_confidence(pred: dict) -> float:
    """Return the scalar confidence value used for summary stats."""
    conf = pred.get("confidence") or []
    if not conf:
        return 0.0
    if CONFIDENCE_MODE == "class0":
        return conf[0]
    # "predicted_class" (default): confidence of whichever class was picked
    return max(conf)


def summarize_predictions(predictions: list, classes: list, threshold) -> dict:
    """Build the resultSummary block from a list of raw predictions."""
    total = len(predictions)
    counts = {cls: 0 for cls in classes}
    conf_values = []
    elapsed_values = []

    for pred in predictions:
        cls = pred.get("prediction")
        if cls in counts:
            counts[cls] += 1
        conf_values.append(prediction_confidence(pred))
        et = pred.get("elapsedTime")
        if et is not None:
            elapsed_values.append(et)

    def stats(values):
        if not values:
            return {"average": 0, "minimum": 0, "maximum": 0}
        return {
            "average": sum(values) / len(values),
            "minimum": min(values),
            "maximum": max(values),
        }

    conf_stats = stats(conf_values)
    time_stats = stats(elapsed_values)

    summary = {
        "dataCount": {"totalCount": total, **counts},
        "confidenceScore": {
            "averageScore": round(conf_stats["average"], 6),
            "minimumScore": round(conf_stats["minimum"], 6),
            "maximumScore": round(conf_stats["maximum"], 6),
        },
        "elapsedTime": {
            "averageTime": round(time_stats["average"], 6),
            "minimumTime": round(time_stats["minimum"], 6),
            "maximumTime": round(time_stats["maximum"], 6),
        },
        "threshold": threshold,
    }
    return summary


def sample_predictions(predictions: list, classes: list) -> dict:
    """Build the sample_results block: up to SAMPLE_SIZE predictions per class."""
    by_class = {cls: [] for cls in classes}
    for pred in predictions:
        cls = pred.get("prediction")
        if cls in by_class:
            by_class[cls].append(pred)

    if SAMPLE_STRATEGY == "highest":
        for cls in by_class:
            by_class[cls].sort(key=prediction_confidence, reverse=True)

    return {cls: preds[:SAMPLE_SIZE] for cls, preds in by_class.items()}


def split_ai_model(ai_model: str):
    """'sidetopsideu8000/sidetopsideu8000_260316_260316081905' ->
    ('sidetopsideu8000', 'sidetopsideu8000_260316_260316081905')"""
    if "/" in ai_model:
        model_name, model_version = ai_model.split("/", 1)
    else:
        model_name, model_version = ai_model, ai_model
    return model_name, model_version


def model_matches(ai_model: str, wanted_models: list, exact: bool) -> bool:
    """True if ai_model (e.g. 'sidetopsideu8000/sidetopsideu8000_260316_260316081905')
    matches one of the requested filters.
    - exact=True  -> ai_model must equal one of wanted_models exactly
    - exact=False -> matches if the modelName part (before '/') equals, or
                      the full aiModel string contains, one of wanted_models
    """
    if not wanted_models:
        return True
    if exact:
        return ai_model in wanted_models
    model_name, _ = split_ai_model(ai_model)
    return any(w == model_name or w in ai_model for w in wanted_models)


def transform_document(src_doc: dict, wanted_models: list = None, exact: bool = False) -> list:
    """Turn ONE source document into a LIST of target documents (one per
    AI model found in inspectionResult.aiResults that matches wanted_models,
    or all of them if wanted_models is empty/None)."""
    metadata = src_doc.get("metadata", {})
    inspection = src_doc.get("inspectionResult", {})
    ai_results = inspection.get("aiResults", [])

    out_docs = []
    for ai_result in ai_results:
        ai_model = ai_result.get("aiModel", "")
        if not model_matches(ai_model, wanted_models, exact):
            continue
        model_name, model_version = split_ai_model(ai_model)
        classes = ai_result.get("classes", [])
        predictions = ai_result.get("predictions", [])

        target_doc = {
            # --- flattened metadata ---
            "gbm": metadata.get("gbm"),
            "process": metadata.get("process"),
            "location": metadata.get("location"),
            "equipmentId": metadata.get("equipmentId"),
            "productId": metadata.get("productId"),
            "createdAt": metadata.get("createdAt"),
            "localTimezone": metadata.get("localTimezone"),
            "mode": metadata.get("mode"),
            "extraInfo": metadata.get("extraInfo", {}),

            # --- per-model info ---
            "modelName": model_name,
            "modelVersion": model_version,
            "task": ai_result.get("task"),
            "classes": classes,

            # --- derived ---
            "resultSummary": summarize_predictions(
                predictions, classes, threshold=predictions[0].get("threshold") if predictions else None
            ),
            "sample_results": sample_predictions(predictions, classes),
        }
        out_docs.append(target_doc)

    return out_docs


# --------------------------------------------------------------------------
# Migration driver
# --------------------------------------------------------------------------

def build_upsert_filter(doc: dict) -> dict:
    """Uniquely identifies a target doc so re-runs update instead of
    duplicating. Adjust the key fields if your notion of 'unique' differs."""
    return {
        "equipmentId": doc.get("equipmentId"),
        "productId": doc.get("productId"),
        "createdAt": doc.get("createdAt"),
        "modelName": doc.get("modelName"),
        "modelVersion": doc.get("modelVersion"),
    }


def parse_date(s: str) -> datetime:
    """Parse 'YYYY-MM-DD' or a full ISO-8601 string into a UTC-aware datetime.
    metadata.createdAt is stored as a BSON date (UTC), so boundaries are
    compared directly against it."""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}', expected YYYY-MM-DD or ISO-8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_query(start_date: datetime = None, end_date: datetime = None,
                 ai_models: list = None, ai_model_exact: bool = False) -> dict:
    """Build the MongoDB filter used to pull ONLY the matching documents from
    the source collection -- never the whole collection."""
    query = {}

    # --- createdAt range filter ---
    date_cond = {}
    if start_date is not None:
        date_cond["$gte"] = start_date
    if end_date is not None:
        date_cond["$lt"] = end_date
    if date_cond:
        query["metadata.createdAt"] = date_cond

    # --- aiModel filter (array field inside inspectionResult.aiResults) ---
    if ai_models:
        if ai_model_exact:
            query["inspectionResult.aiResults.aiModel"] = {"$in": ai_models}
        else:
            # matches if aiModel starts with any requested model name, e.g.
            # "sidetopsideu8000" matches
            # "sidetopsideu8000/sidetopsideu8000_260316_260316081905"
            query["inspectionResult.aiResults.aiModel"] = {
                "$regex": "|".join(f"^{m}" for m in ai_models)
            }

    return query


def run(dry_run: bool = False, limit: int = 0, query: dict = None,
        wanted_models: list = None, ai_model_exact: bool = False):
    query = query or {}
    src_client = MongoClient(SRC_URI)
    dst_client = MongoClient(DST_URI)

    src_coll = src_client[SRC_DB][SRC_COLLECTION]
    dst_coll = dst_client[DST_DB][DST_COLLECTION]

    log.info("Source query: %s", query)
    cursor = src_coll.find(query, batch_size=BATCH_SIZE)
    if limit:
        cursor = cursor.limit(limit)

    total_src = 0
    total_out = 0
    ops = []

    def flush_ops():
        nonlocal ops, total_out
        if not ops:
            return
        if dry_run:
            log.info("[dry-run] would write %d docs", len(ops))
        else:
            try:
                result = dst_coll.bulk_write(ops, ordered=False)
                total_out += result.upserted_count + result.modified_count + result.matched_count
            except PyMongoError:
                log.exception("bulk_write failed for a batch")
        ops = []

    for src_doc in cursor:
        total_src += 1
        try:
            target_docs = transform_document(src_doc, wanted_models=wanted_models, exact=ai_model_exact)
        except Exception:
            log.exception("Failed to transform source _id=%s", src_doc.get("_id"))
            continue

        for t_doc in target_docs:
            if dry_run:
                log.info("Transformed doc: %s", {k: t_doc[k] for k in ("productId", "modelName", "resultSummary")})
            filt = build_upsert_filter(t_doc)
            ops.append(UpdateOne(filt, {"$set": t_doc}, upsert=True))

        if len(ops) >= BATCH_SIZE:
            flush_ops()

        if total_src % 1000 == 0:
            log.info("Processed %d source documents...", total_src)

    flush_ops()

    log.info("Done. Source docs read: %d, target docs written/upserted: %d", total_src, total_out)

    src_client.close()
    dst_client.close()


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dry-run", action="store_true", help="Transform and log but do not write to destination")
    p.add_argument("--limit", type=int, default=0, help="Only process the first N matched source documents (0 = all)")

    p.add_argument("--start-date", type=parse_date, default=None,
                    help="Only include docs with metadata.createdAt >= this date (YYYY-MM-DD or ISO-8601)")
    p.add_argument("--end-date", type=parse_date, default=None,
                    help="Only include docs with metadata.createdAt < this date (YYYY-MM-DD or ISO-8601)")

    p.add_argument("--ai-model", action="append", default=None, dest="ai_models",
                    help="Only include this AI model (aiResults.aiModel). Repeatable, e.g. "
                         "--ai-model sidetopsideu8000 --ai-model sidebottom. "
                         "By default matches the modelName prefix; use --ai-model-exact for an exact match "
                         "on the full 'modelName/modelVersion' string.")
    p.add_argument("--ai-model-exact", action="store_true",
                    help="Require --ai-model values to exactly equal the full aiModel string")

    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    log.info(
        "Source: %s / %s.%s  ->  Destination: %s / %s.%s",
        SRC_URI, SRC_DB, SRC_COLLECTION, DST_URI, DST_DB, DST_COLLECTION,
    )

    mongo_query = build_query(
        start_date=args.start_date,
        end_date=args.end_date,
        ai_models=args.ai_models,
        ai_model_exact=args.ai_model_exact,
    )

    run(
        dry_run=args.dry_run,
        limit=args.limit,
        query=mongo_query,
        wanted_models=args.ai_models,
        ai_model_exact=args.ai_model_exact,
    )
