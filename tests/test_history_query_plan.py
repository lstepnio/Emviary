from emviary.store import Store


def test_history_and_navigation_do_not_sort_manifests_in_temp_storage(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    with store.connect() as db:
        for comparison, direction in (("<", "DESC"), (">", "ASC")):
            plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM images "
                f"WHERE frame_id=? AND hidden=0 AND id{comparison}? ORDER BY id {direction}",
                ("frame", 100),
            ).fetchall()
            assert not any("TEMP B-TREE" in row[3] for row in plan)


def test_existing_database_gains_history_index_idempotently(tmp_path):
    path = tmp_path / "existing.sqlite3"
    store = Store(path)
    with store.connect() as db:
        db.execute("DROP INDEX images_frame_hidden_id")
    Store(path)
    Store(path)
    with store.connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            len(
                [
                    row
                    for row in db.execute("PRAGMA index_list(images)")
                    if row[1] == "images_frame_hidden_id"
                ]
            )
            == 1
        )
