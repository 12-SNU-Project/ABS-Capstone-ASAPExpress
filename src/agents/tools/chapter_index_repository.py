"""Chapter index read adapter for pre-classification routing."""

from __future__ import annotations

from typing import Mapping


def LoadPreClassificationChapterRows() -> tuple[Mapping[str, object], ...]:
    """Load cn_chapter_index rows through the current DB helper.

    ponytail: this is the temporary DB boundary; replace this module when the
    shared DBConnection component lands.
    """
    try:
        from agents import document_package as db
    except (Exception, SystemExit):
        return ()

    conn: object | None = None
    try:
        conn = db._connect_db()
        cur = conn.cursor()
        try:
            if not db._table_exists(cur, "cn_chapter_index"):
                return ()
            cur.execute("SELECT * FROM cn_chapter_index ORDER BY chapter")
            columns = tuple(str(column[0]) for column in cur.description)
            rows = cur.fetchall()
            return tuple(
                dict(zip(columns, row))
                for row in rows
            )
        finally:
            cur.close()
    except Exception:
        return ()
    finally:
        db._release_db(conn)
