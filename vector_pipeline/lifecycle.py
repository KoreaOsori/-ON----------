from datetime import datetime, timedelta, timezone

from vector_store import check_config, connect, lock, publish_run


def rollback(config, run_id, reason):
    if not reason.strip():
        raise ValueError("롤백 사유가 필요합니다.")
    with connect() as conn:
        lock(conn)
        check_config(conn, config)
        row = conn.execute("SELECT manifest FROM product_search.ingestion_runs WHERE run_id=%s", (run_id,)).fetchone()
        if not row:
            raise ValueError("롤백할 run이 없습니다.")
        publish_run(conn, run_id, row[0], rollback=True, reason=reason)
    return {"rolled_back_to": run_id, "reason": reason}


def prune_candidates(rows, active, keep_last, older_than_days, include_incomplete=False, now=None):
    if keep_last < 1 or older_than_days < 0:
        raise ValueError("keep-last는 1 이상, older-than-days는 0 이상이어야 합니다.")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=older_than_days)
    completed = sorted((r for r in rows if r[1] == "complete"), key=lambda r: (r[2], r[0]), reverse=True)
    protected = {r[0] for r in completed[:keep_last]} | {active}
    return [r[0] for r in rows if r[0] not in protected and (
        r[1] == "pruning" or (r[2] <= cutoff and (r[1] == "complete" or include_incomplete)))]


def prune(config, keep_last=2, older_than_days=30, apply=False, include_incomplete=False, batch_size=1000):
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch-size는 1~1000이어야 합니다.")
    with connect() as conn:
        lock(conn)
        check_config(conn, config)
        active = conn.execute("SELECT run_id FROM product_search.active_snapshot WHERE singleton").fetchone()
        rows = conn.execute("SELECT run_id,status,updated_at FROM product_search.ingestion_runs").fetchall()
        targets = prune_candidates(rows, active[0] if active else None, keep_last, older_than_days, include_incomplete)
        if not apply:
            return {"dry_run": True, "runs_to_delete": targets, "active_run": active[0] if active else None,
                    "orphan_vectors": conn.execute("SELECT count(*) FROM product_search.product_vectors v WHERE NOT EXISTS "
                                                   "(SELECT 1 FROM product_search.product_links l WHERE l.content_hash=v.content_hash)").fetchone()[0]}
        deleted_links = deleted_vectors = 0
        for run_id in targets:
            # Durable state blocks resuming/publishing a partially pruned run after a crash.
            conn.execute("UPDATE product_search.ingestion_runs SET status='pruning' WHERE run_id=%s", (run_id,))
            while True:
                result = conn.execute("DELETE FROM product_search.product_links WHERE run_id=%s AND chunk_id IN "
                                      "(SELECT chunk_id FROM product_search.product_links WHERE run_id=%s LIMIT %s)",
                                      (run_id, run_id, batch_size))
                deleted_links += result.rowcount
                if result.rowcount == 0:
                    break
            conn.execute("DELETE FROM product_search.ingestion_runs WHERE run_id=%s", (run_id,))
        # Vectors for partially loaded runs may not have links yet: retain them for resume.
        pending = conn.execute("SELECT EXISTS(SELECT 1 FROM product_search.ingestion_runs WHERE status='loading')").fetchone()[0]
        if not pending:
            while True:
                result = conn.execute("DELETE FROM product_search.product_vectors WHERE content_hash IN "
                                      "(SELECT v.content_hash FROM product_search.product_vectors v WHERE NOT EXISTS "
                                      "(SELECT 1 FROM product_search.product_links l WHERE l.content_hash=v.content_hash) LIMIT %s)", (batch_size,))
                deleted_vectors += result.rowcount
                if result.rowcount == 0:
                    break
    return {"dry_run": False, "deleted_runs": targets, "deleted_links": deleted_links,
            "deleted_vectors": deleted_vectors, "vector_gc_deferred_for_loading_runs": pending}
