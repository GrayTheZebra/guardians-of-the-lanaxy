import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self):
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT '',
                    guardian_id TEXT NOT NULL DEFAULT '',
                    device_id TEXT NOT NULL DEFAULT '',
                    guardian_name TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL,
                    response_time INTEGER NOT NULL DEFAULT 0,
                    old_status TEXT NOT NULL DEFAULT '',
                    new_status TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_guardian ON events(guardian_id);
                CREATE INDEX IF NOT EXISTS idx_events_level ON events(level);

                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    guardian_id TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    response_time INTEGER NOT NULL DEFAULT 0,
                    uptime REAL NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_metrics_gt
                    ON metrics(guardian_id, timestamp);

                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guardian_id TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT '',
                    guardian_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    severity TEXT NOT NULL DEFAULT 'warning',
                    level INTEGER NOT NULL DEFAULT 1,
                    message TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT '',
                    acknowledged_at TEXT NOT NULL DEFAULT '',
                    acknowledged_by TEXT NOT NULL DEFAULT '',
                    acknowledge_note TEXT NOT NULL DEFAULT '',
                    notification_count INTEGER NOT NULL DEFAULT 0,
                    last_notification_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_guardian_status
                    ON incidents(guardian_id, status);
                CREATE INDEX IF NOT EXISTS idx_incidents_started
                    ON incidents(started_at);

                CREATE TABLE IF NOT EXISTS incident_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    guardian_id TEXT NOT NULL,
                    guardian_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'blocked',
                    message TEXT NOT NULL DEFAULT '',
                    joined_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(incident_id, guardian_id)
                );
                CREATE INDEX IF NOT EXISTS idx_incident_members_incident
                    ON incident_members(incident_id, status);
                CREATE INDEX IF NOT EXISTS idx_incident_members_guardian
                    ON incident_members(guardian_id, status);

                CREATE TABLE IF NOT EXISTS incident_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_kind TEXT NOT NULL DEFAULT '',
                    guardian_id TEXT NOT NULL DEFAULT '',
                    guardian_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_incident_timeline_incident
                    ON incident_timeline(incident_id, timestamp);

                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    incident_id INTEGER,
                    guardian_id TEXT NOT NULL DEFAULT '',
                    event_kind TEXT NOT NULL DEFAULT '',
                    rule_id TEXT NOT NULL DEFAULT '',
                    rule_name TEXT NOT NULL DEFAULT '',
                    channel_id TEXT NOT NULL DEFAULT '',
                    channel_name TEXT NOT NULL DEFAULT '',
                    channel_type TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_deliveries_time
                    ON notification_deliveries(timestamp);
                CREATE INDEX IF NOT EXISTS idx_deliveries_channel
                    ON notification_deliveries(channel_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_deliveries_incident
                    ON notification_deliveries(incident_id);

                CREATE TABLE IF NOT EXISTS notification_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    incident_id INTEGER,
                    rule_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    rule_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    completed_at TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_notification_jobs_due
                    ON notification_jobs(status, due_at);
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(incidents)").fetchall()}
            if "recurrence_count" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN recurrence_count INTEGER NOT NULL DEFAULT 1")
            if "previous_incident_id" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN previous_incident_id INTEGER")
            if "correlation_key" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN correlation_key TEXT NOT NULL DEFAULT ''")
            if "priority" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
            if "assignee" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN assignee TEXT NOT NULL DEFAULT ''")
            if "merged_into" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN merged_into INTEGER")
            if "confidence" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN confidence INTEGER NOT NULL DEFAULT 0")
            # Die frühere manuelle Merge-Funktion wurde entfernt. Bereits
            # zusammengeführte Incidents werden wieder als beendet behandelt.
            connection.execute("UPDATE incidents SET status='resolved', merged_into=NULL WHERE status='merged'")

    @staticmethod
    def now():
        return datetime.now().isoformat(timespec="seconds")

    def add_event(self, event_type, message, level=0, status="",
                  guardian_id="", device_id="", guardian_name="",
                  response_time=0, old_status="", new_status="",
                  details=None, timestamp=None):
        with self.connect() as connection:
            connection.execute("""
                INSERT INTO events (
                    timestamp,event_type,level,status,guardian_id,device_id,
                    guardian_name,message,response_time,old_status,new_status,
                    details_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                timestamp or self.now(), event_type, int(level), status,
                guardian_id, device_id, guardian_name, message,
                int(response_time or 0), old_status, new_status,
                json.dumps(details or {}, ensure_ascii=False)
            ))

    def add_result(self, result, log_event=True):
        with self.connect() as connection:
            connection.execute("""
                INSERT INTO metrics (
                    timestamp,guardian_id,device_id,status,level,response_time,
                    uptime,details_json
                ) VALUES (?,?,?,?,?,?,?,?)
            """, (
                result.last_check, result.id, result.device_id, result.status,
                result.level, int(result.response_time or 0),
                float(result.uptime or 0),
                json.dumps(result.details or {}, ensure_ascii=False)
            ))
        if log_event:
            self.add_event(
                "CHECK", result.message, result.level, result.status,
                result.id, result.device_id, result.name,
                result.response_time, details=result.to_dict(),
                timestamp=result.last_check
            )

    def add_status_change(self, result, old_status, new_status):
        self.add_event(
            "STATUS_CHANGED",
            f"{result.name}: {old_status or 'unbekannt'} → {new_status} – {result.message}",
            result.level, result.status, result.id, result.device_id,
            result.name, result.response_time, old_status, new_status,
            result.to_dict()
        )


    def _timeline(self, connection, incident_id, event_kind, timestamp,
                  guardian_id="", guardian_name="", status="", message="",
                  actor="", details=None):
        connection.execute(
            """
            INSERT INTO incident_timeline (
                incident_id,timestamp,event_kind,guardian_id,guardian_name,
                status,message,actor,details_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                int(incident_id), timestamp, event_kind, guardian_id,
                guardian_name, status, message, actor,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    def _open_incident_for_guardian(self, connection, guardian_id):
        row = connection.execute(
            """
            SELECT * FROM incidents
            WHERE guardian_id=? AND status='open'
            ORDER BY id DESC LIMIT 1
            """,
            (guardian_id,),
        ).fetchone()
        if row:
            return row
        return connection.execute(
            """
            SELECT i.* FROM incidents i
            JOIN incident_members m ON m.incident_id=i.id
            WHERE m.guardian_id=? AND m.status!='resolved' AND i.status='open'
            ORDER BY i.id DESC LIMIT 1
            """,
            (guardian_id,),
        ).fetchone()

    def sync_incident(self, event):
        old_status = str(getattr(event, "old_status", "") or "")
        new_status = str(getattr(event, "new_status", "") or "")
        guardian_id = str(getattr(event, "source", "") or "")
        now = getattr(event, "timestamp", None) or self.now()
        details = getattr(event, "details", {}) or {}
        guardian_name = details.get("name", guardian_id)
        device_id = str(getattr(event, "device_id", "") or "")
        message = str(getattr(event, "message", "") or "")
        blocked_by = str(details.get("blocked_by", "") or "")

        with self.connect() as connection:
            if new_status == "blocked" and blocked_by:
                root = self._open_incident_for_guardian(connection, blocked_by)
                if root:
                    connection.execute(
                        """
                        INSERT INTO incident_members (
                            incident_id,guardian_id,guardian_name,status,message,
                            joined_at,updated_at,resolved_at
                        ) VALUES (?,?,?,?,?,?,?, '')
                        ON CONFLICT(incident_id,guardian_id) DO UPDATE SET
                            guardian_name=excluded.guardian_name,
                            status=excluded.status,message=excluded.message,
                            updated_at=excluded.updated_at,resolved_at=''
                        """,
                        (
                            root["id"], guardian_id, guardian_name, "blocked",
                            message, now, now,
                        ),
                    )
                    connection.execute(
                        "UPDATE incidents SET updated_at=? WHERE id=?",
                        (now, root["id"]),
                    )
                    self._timeline(
                        connection, root["id"], "affected", now,
                        guardian_id, guardian_name, new_status, message,
                        details=details,
                    )
                    return {
                        "id": root["id"], "status": "open",
                        "started_at": root["started_at"],
                        "acknowledged": bool(root["acknowledged_at"]),
                        "suppressed": True,
                    }

            if new_status in {"critical", "warning", "blocked"}:
                severity = "critical" if new_status == "critical" else "warning"
                root_cause_id = str(details.get("root_cause_id", "") or "")
                if root_cause_id and root_cause_id != guardian_id:
                    root = self._open_incident_for_guardian(connection, root_cause_id)
                    if root:
                        connection.execute(
                            """
                            INSERT INTO incident_members (
                                incident_id,guardian_id,guardian_name,status,message,
                                joined_at,updated_at,resolved_at
                            ) VALUES (?,?,?,?,?,?,?, '')
                            ON CONFLICT(incident_id,guardian_id) DO UPDATE SET
                                guardian_name=excluded.guardian_name,
                                status=excluded.status,message=excluded.message,
                                updated_at=excluded.updated_at,resolved_at=''
                            """,
                            (root["id"], guardian_id, guardian_name, new_status, message, now, now),
                        )
                        connection.execute("UPDATE incidents SET updated_at=? WHERE id=?", (now, root["id"]))
                        self._timeline(connection, root["id"], "correlated", now, guardian_id, guardian_name, new_status, message, details=details)
                        return {"id":root["id"],"status":"open","started_at":root["started_at"],"acknowledged":bool(root["acknowledged_at"]),"suppressed":True,"root_cause_id":root_cause_id}
                row = connection.execute(
                    """
                    SELECT * FROM incidents
                    WHERE guardian_id=? AND status='open'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (guardian_id,),
                ).fetchone()
                if row:
                    connection.execute(
                        """
                        UPDATE incidents
                        SET severity=?, level=?, message=?, updated_at=?,
                            guardian_name=?, device_id=?
                        WHERE id=?
                        """,
                        (
                            severity, int(getattr(event, "level", 1) or 1),
                            message, now, guardian_name, device_id, row["id"],
                        ),
                    )
                    incident_id = row["id"]
                    started_at = row["started_at"]
                    acknowledged = bool(row["acknowledged_at"])
                    event_kind = "updated"
                else:
                    previous = connection.execute(
                        """
                        SELECT id,recurrence_count,resolved_at FROM incidents
                        WHERE guardian_id=? AND status='resolved'
                          AND resolved_at!=''
                          AND julianday(?) - julianday(resolved_at) <= 7
                        ORDER BY resolved_at DESC,id DESC LIMIT 1
                        """,
                        (guardian_id, now),
                    ).fetchone()
                    recurrence_count = int(previous["recurrence_count"] or 1) + 1 if previous else 1
                    previous_incident_id = int(previous["id"]) if previous else None
                    correlation_key = str(details.get("correlation_key") or device_id or guardian_id)
                    cursor = connection.execute(
                        """
                        INSERT INTO incidents (
                            guardian_id,device_id,guardian_name,status,
                            severity,level,message,started_at,updated_at,
                            recurrence_count,previous_incident_id,correlation_key
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            guardian_id, device_id, guardian_name, "open",
                            severity, int(getattr(event, "level", 1) or 1),
                            message, now, now, recurrence_count,
                            previous_incident_id, correlation_key,
                        ),
                    )
                    incident_id = cursor.lastrowid
                    started_at = now
                    acknowledged = False
                    event_kind = "recurring" if previous else "opened"
                self._timeline(
                    connection, incident_id, event_kind, now, guardian_id,
                    guardian_name, new_status, message, details=details,
                )
                return {
                    "id": incident_id, "status": "open",
                    "started_at": started_at,
                    "acknowledged": acknowledged,
                }

            if new_status == "maintenance":
                row = self._open_incident_for_guardian(connection, guardian_id)
                if row:
                    self._timeline(
                        connection, row["id"], "maintenance", now,
                        guardian_id, guardian_name, new_status, message,
                        details=details,
                    )
                return None

            if new_status == "ok" and old_status in {
                "critical", "warning", "blocked", "maintenance",
            }:
                member = connection.execute(
                    """
                    SELECT m.*, i.started_at, i.acknowledged_at
                    FROM incident_members m
                    JOIN incidents i ON i.id=m.incident_id
                    WHERE m.guardian_id=? AND m.status!='resolved'
                      AND i.status='open'
                    ORDER BY m.id DESC LIMIT 1
                    """,
                    (guardian_id,),
                ).fetchone()
                if member:
                    connection.execute(
                        """
                        UPDATE incident_members SET status='resolved',
                            resolved_at=?,updated_at=?,message=? WHERE id=?
                        """,
                        (now, now, message, member["id"]),
                    )
                    self._timeline(
                        connection, member["incident_id"], "affected_recovered",
                        now, guardian_id, guardian_name, new_status, message,
                        details=details,
                    )
                    return None

                row = connection.execute(
                    """
                    SELECT * FROM incidents
                    WHERE guardian_id=? AND status='open'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (guardian_id,),
                ).fetchone()
                if not row:
                    return None
                connection.execute(
                    """
                    UPDATE incidents SET status='resolved', resolved_at=?,
                        updated_at=?, message=? WHERE id=?
                    """,
                    (now, now, message, row["id"]),
                )
                connection.execute(
                    """
                    UPDATE incident_members SET status='resolved',
                        resolved_at=?,updated_at=?
                    WHERE incident_id=? AND status!='resolved'
                    """,
                    (now, now, row["id"]),
                )
                self._timeline(
                    connection, row["id"], "resolved", now, guardian_id,
                    guardian_name, new_status, message, details=details,
                )
                try:
                    duration_seconds = max(0, int((
                        datetime.fromisoformat(now)
                        - datetime.fromisoformat(row["started_at"])
                    ).total_seconds()))
                except (TypeError, ValueError):
                    duration_seconds = 0
                return {
                    "id": row["id"], "status": "resolved",
                    "started_at": row["started_at"], "resolved_at": now,
                    "duration_seconds": duration_seconds,
                    "acknowledged": bool(row["acknowledged_at"]),
                }
        return None

    def get_incident(self, incident_id):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT i.*,
                    (SELECT COUNT(*) FROM incident_members m
                     WHERE m.incident_id=i.id) AS affected_count
                FROM incidents i WHERE i.id=?
                """,
                (int(incident_id),),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["members"] = [dict(item) for item in connection.execute(
                """
                SELECT * FROM incident_members WHERE incident_id=?
                ORDER BY CASE status WHEN 'blocked' THEN 0 ELSE 1 END,
                         joined_at, guardian_name
                """,
                (int(incident_id),),
            ).fetchall()]
            result["timeline"] = [dict(item) for item in connection.execute(
                """
                SELECT * FROM incident_timeline WHERE incident_id=?
                ORDER BY timestamp DESC,id DESC
                """,
                (int(incident_id),),
            ).fetchall()]
        return result

    def get_open_incident(self, guardian_id):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM incidents
                WHERE guardian_id=? AND status='open'
                ORDER BY id DESC LIMIT 1
                """,
                (guardian_id,),
            ).fetchone()
        return dict(row) if row else None

    def query_incidents(
        self,
        status="",
        guardian_id="",
        priority="",
        acknowledged="",
        assignee="",
        page=1,
        per_page=50,
    ):
        where = []
        params = []
        if status:
            where.append("i.status=?")
            params.append(status)
        if guardian_id:
            where.append("i.guardian_id=?")
            params.append(guardian_id)
        if priority:
            where.append("i.priority=?")
            params.append(priority)
        if acknowledged == "yes":
            where.append("i.acknowledged_at!=''")
        elif acknowledged == "no":
            where.append("i.acknowledged_at=''")
        if assignee:
            where.append("i.assignee LIKE ?")
            params.append(f"%{assignee}%")
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        page = max(1, int(page))
        per_page = max(1, min(200, int(per_page)))
        offset = (page - 1) * per_page
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM incidents i{where_sql}",
                params,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT i.*,
                    (SELECT COUNT(*) FROM incident_members m
                     WHERE m.incident_id=i.id) AS affected_count,
                    CASE
                        WHEN resolved_at!='' THEN
                            CAST(
                                (julianday(resolved_at)-julianday(started_at))
                                * 86400 AS INTEGER
                            )
                        ELSE
                            CAST(
                                (julianday('now','localtime')-julianday(started_at))
                                * 86400 AS INTEGER
                            )
                    END AS duration_seconds
                FROM incidents i
                {where_sql}
                ORDER BY
                    CASE status WHEN 'open' THEN 0 ELSE 1 END,
                    started_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, per_page, offset],
            ).fetchall()
        return {
            "rows": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }


    def delete_incidents_for_guardian(self, guardian_id):
        """Delete incidents owned by a Guardian and detach it from correlated incidents."""
        guardian_id = str(guardian_id or "").strip()
        if not guardian_id:
            return {"incidents": 0, "members": 0}

        with self.connect() as connection:
            primary_ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT id FROM incidents WHERE guardian_id=?",
                    (guardian_id,),
                ).fetchall()
            ]
            member_count = int(connection.execute(
                "SELECT COUNT(*) FROM incident_members WHERE guardian_id=?",
                (guardian_id,),
            ).fetchone()[0])

            if primary_ids:
                placeholders = ",".join("?" for _ in primary_ids)
                connection.execute(
                    f"DELETE FROM notification_jobs WHERE incident_id IN ({placeholders})",
                    primary_ids,
                )
                connection.execute(
                    f"DELETE FROM notification_deliveries WHERE incident_id IN ({placeholders})",
                    primary_ids,
                )
                connection.execute(
                    f"DELETE FROM incident_timeline WHERE incident_id IN ({placeholders})",
                    primary_ids,
                )
                connection.execute(
                    f"DELETE FROM incident_members WHERE incident_id IN ({placeholders})",
                    primary_ids,
                )
                connection.execute(
                    f"DELETE FROM incidents WHERE id IN ({placeholders})",
                    primary_ids,
                )

            # A Guardian can also be an affected member of an incident whose
            # primary cause is a different Guardian. Detach only that member.
            connection.execute(
                "DELETE FROM incident_members WHERE guardian_id=?",
                (guardian_id,),
            )
            connection.execute(
                "DELETE FROM incident_timeline WHERE guardian_id=?",
                (guardian_id,),
            )
            connection.execute(
                "DELETE FROM notification_deliveries WHERE guardian_id=?",
                (guardian_id,),
            )

        return {"incidents": len(primary_ids), "members": member_count}

    def add_incident_note(self, incident_id, actor, note):
        note = str(note or "").strip()
        if not note:
            raise ValueError("Notiz darf nicht leer sein.")
        now = self.now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM incidents WHERE id=?", (int(incident_id),)
            ).fetchone()
            if not row:
                raise ValueError("Incident nicht gefunden.")
            self._timeline(
                connection, incident_id, "note", now,
                row["guardian_id"], row["guardian_name"], row["status"],
                note, actor=actor,
            )
            connection.execute(
                "UPDATE incidents SET updated_at=? WHERE id=?",
                (now, int(incident_id)),
            )
        return self.get_incident(incident_id)

    def acknowledge_incident(self, incident_id, actor="", note=""):
        incident_id = int(incident_id)
        now = self.now()
        actor = str(actor or "")
        note = str(note or "")

        # Use an explicit write transaction. A successful UI response must only
        # be returned after the acknowledgement has been committed and read
        # back from SQLite.
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM incidents WHERE id=?",
                (incident_id,),
            ).fetchone()
            if not row:
                raise ValueError("Incident nicht gefunden.")

            cursor = connection.execute(
                """
                UPDATE incidents
                SET acknowledged_at=?, acknowledged_by=?,
                    acknowledge_note=?, updated_at=?
                WHERE id=?
                """,
                (now, actor, note, now, incident_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Quittierung konnte nicht gespeichert werden.")

            self._timeline(
                connection, incident_id, "acknowledged", now,
                row["guardian_id"], row["guardian_name"], row["status"],
                note or "Incident wurde quittiert.", actor=actor,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        # Verify through a fresh connection so WAL/transaction errors cannot
        # produce a false positive in the web interface.
        persisted = self.get_incident(incident_id)
        if not persisted or persisted.get("acknowledged_at") != now:
            raise RuntimeError(
                "Quittierung wurde nicht dauerhaft in der Datenbank gespeichert."
            )

        self.cancel_notification_jobs(
            incident_id=incident_id,
            reason="Incident wurde quittiert.",
        )
        return persisted

    def unacknowledge_incident(self, incident_id):
        now = self.now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM incidents WHERE id=?",
                (int(incident_id),),
            ).fetchone()
            if not row:
                raise ValueError("Incident nicht gefunden.")
            connection.execute(
                """
                UPDATE incidents
                SET acknowledged_at='', acknowledged_by='',
                    acknowledge_note='', updated_at=?
                WHERE id=?
                """,
                (now, int(incident_id)),
            )
            self._timeline(
                connection, incident_id, "unacknowledged", now,
                row["guardian_id"], row["guardian_name"], row["status"],
                "Quittierung wurde aufgehoben.",
            )
        return self.get_incident(incident_id)

    def update_incident_metadata(self, incident_id, actor="", priority=None, assignee=None):
        now=self.now()
        with self.connect() as connection:
            row=connection.execute("SELECT * FROM incidents WHERE id=?",(int(incident_id),)).fetchone()
            if not row: raise ValueError("Incident nicht gefunden.")
            values={"priority":row["priority"],"assignee":row["assignee"]}
            if priority is not None:
                if priority not in {"low","normal","high","critical"}: raise ValueError("Ungültige Priorität.")
                values["priority"]=priority
            if assignee is not None: values["assignee"]=str(assignee).strip()[:255]
            connection.execute("UPDATE incidents SET priority=?,assignee=?,updated_at=? WHERE id=?",(values["priority"],values["assignee"],now,int(incident_id)))
            self._timeline(connection,incident_id,"metadata",now,row["guardian_id"],row["guardian_name"],row["status"],f"Priorität: {values['priority']}, Verantwortlicher: {values['assignee'] or 'nicht zugewiesen'}",actor=actor)
        return self.get_incident(incident_id)

    def split_incident_member(self, incident_id, guardian_id, actor=""):
        now=self.now()
        with self.connect() as connection:
            member=connection.execute("SELECT * FROM incident_members WHERE incident_id=? AND guardian_id=?",(int(incident_id),guardian_id)).fetchone()
            if not member: raise ValueError("Betroffenes System nicht gefunden.")
            cursor=connection.execute("INSERT INTO incidents (guardian_id,guardian_name,status,severity,level,message,started_at,updated_at,priority,correlation_key) VALUES (?,?,?,?,?,?,?,?,?,?)",(member["guardian_id"],member["guardian_name"],"open" if member["status"]!="resolved" else "resolved","warning",1,member["message"],member["joined_at"],now,"normal",member["guardian_id"]))
            new_id=cursor.lastrowid
            connection.execute("DELETE FROM incident_members WHERE incident_id=? AND guardian_id=?",(int(incident_id),guardian_id))
            self._timeline(connection,incident_id,"split",now,member["guardian_id"],member["guardian_name"],member["status"],f"System wurde als Incident #{new_id} abgetrennt.",actor=actor)
        return new_id

    def record_delivery(
        self,
        payload,
        rule,
        channel,
        success,
        error="",
    ):
        incident_id = payload.get("incident_id")
        now = self.now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_deliveries (
                    timestamp,incident_id,guardian_id,event_kind,
                    rule_id,rule_name,channel_id,channel_name,
                    channel_type,success,error,payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now,
                    int(incident_id) if incident_id else None,
                    payload.get("source", ""),
                    payload.get("kind", ""),
                    rule.get("id", ""),
                    rule.get("name", ""),
                    channel.get("id", ""),
                    channel.get("name", ""),
                    channel.get("type", ""),
                    1 if success else 0,
                    error,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            if incident_id and success:
                connection.execute(
                    """
                    UPDATE incidents
                    SET notification_count=notification_count+1,
                        last_notification_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (now, now, int(incident_id)),
                )

    def query_deliveries(
        self,
        channel_id="",
        incident_id=None,
        page=1,
        per_page=100,
    ):
        where = []
        params = []
        if channel_id:
            where.append("channel_id=?")
            params.append(channel_id)
        if incident_id:
            where.append("incident_id=?")
            params.append(int(incident_id))
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        page = max(1, int(page))
        per_page = max(1, min(250, int(per_page)))
        offset = (page - 1) * per_page
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM notification_deliveries{where_sql}",
                params,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM notification_deliveries
                {where_sql}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, per_page, offset],
            ).fetchall()
        return {
            "rows": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def create_notification_job(
        self,
        due_at,
        source,
        incident_id,
        rule,
        payload,
    ):
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO notification_jobs (
                    created_at,due_at,source,incident_id,rule_id,
                    payload_json,rule_json,status
                ) VALUES (?,?,?,?,?,?,?,'pending')
                """,
                (
                    self.now(),
                    due_at,
                    source,
                    int(incident_id) if incident_id else None,
                    rule.get("id", ""),
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(rule, ensure_ascii=False),
                ),
            )
        return cursor.lastrowid

    def pending_notification_jobs(self):
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM notification_jobs
                WHERE status='pending'
                ORDER BY due_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_notification_job(self, job_id, error=""):
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE notification_jobs
                SET status=?, completed_at=?, error=?
                WHERE id=?
                """,
                (
                    "failed" if error else "completed",
                    self.now(),
                    error,
                    int(job_id),
                ),
            )

    def notification_job_is_pending(self, job_id):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM notification_jobs WHERE id=?",
                (int(job_id),),
            ).fetchone()
        return bool(row and row["status"] == "pending")

    def cancel_notification_jobs(
        self,
        source="",
        incident_id=None,
        reason="Abgebrochen.",
    ):
        where = ["status='pending'"]
        params = []
        if source:
            where.append("source=?")
            params.append(source)
        if incident_id:
            where.append("incident_id=?")
            params.append(int(incident_id))
        if len(where) == 1:
            return 0
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE notification_jobs
                SET status='cancelled', completed_at=?, error=?
                WHERE {' AND '.join(where)}
                """,
                [self.now(), reason, *params],
            )
        return cursor.rowcount

    def cleanup(self, retention_days=90):
        cutoff = (datetime.now() - timedelta(days=max(1, retention_days))).isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            connection.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
            connection.execute(
                "DELETE FROM notification_deliveries WHERE timestamp < ?",
                (cutoff,),
            )
            connection.execute(
                """
                DELETE FROM notification_jobs
                WHERE created_at < ? AND status!='pending'
                """,
                (cutoff,),
            )

    def maintenance_stats(self):
        with self.connect() as connection:
            events = connection.execute(
                "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM events"
            ).fetchone()
            metrics = connection.execute(
                "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM metrics"
            ).fetchone()

        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "path": str(self.path),
            "size": size,
            "events": {
                "count": events[0],
                "oldest": events[1] or "",
                "newest": events[2] or "",
            },
            "metrics": {
                "count": metrics[0],
                "oldest": metrics[1] or "",
                "newest": metrics[2] or "",
            },
        }

    def clear_events(self):
        with self.connect() as connection:
            deleted = connection.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
            connection.execute("DELETE FROM events")
        return deleted

    def clear_metrics(self):
        with self.connect() as connection:
            deleted = connection.execute(
                "SELECT COUNT(*) FROM metrics"
            ).fetchone()[0]
            connection.execute("DELETE FROM metrics")
        return deleted

    def vacuum(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("VACUUM")
        finally:
            connection.close()

    def cleanup_with_counts(self, retention_days=90):
        cutoff = (
            datetime.now()
            - timedelta(days=max(1, int(retention_days)))
        ).isoformat(timespec="seconds")

        with self.connect() as connection:
            events = connection.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp < ?",
                (cutoff,),
            ).fetchone()[0]
            metrics = connection.execute(
                "SELECT COUNT(*) FROM metrics WHERE timestamp < ?",
                (cutoff,),
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM events WHERE timestamp < ?",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM metrics WHERE timestamp < ?",
                (cutoff,),
            )

        return {
            "events": events,
            "metrics": metrics,
            "cutoff": cutoff,
        }

    def query_events(self, search="", guardian_id="", level="", event_type="",
                     date_from="", date_to="", page=1, per_page=100):
        where, params = [], []
        if search:
            where.append("(message LIKE ? OR guardian_name LIKE ? OR guardian_id LIKE ?)")
            token = f"%{search}%"
            params += [token, token, token]
        if guardian_id:
            where.append("guardian_id = ?"); params.append(guardian_id)
        if level != "":
            where.append("level = ?"); params.append(int(level))
        if event_type:
            where.append("event_type = ?"); params.append(event_type)
        if date_from:
            where.append("timestamp >= ?"); params.append(date_from + "T00:00:00")
        if date_to:
            where.append("timestamp <= ?"); params.append(date_to + "T23:59:59")
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        page, per_page = max(1, int(page)), min(1000, max(10, int(per_page)))
        offset = (page - 1) * per_page
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM events {where_sql}", params
            ).fetchone()[0]
            rows = connection.execute(f"""
                SELECT * FROM events {where_sql}
                ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?
            """, [*params, per_page, offset]).fetchall()
        return {
            "rows": [dict(row) for row in rows], "total": total,
            "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page)
        }

    def filter_values(self):
        with self.connect() as connection:
            guardians = connection.execute("""
                SELECT DISTINCT guardian_id,guardian_name FROM events
                WHERE guardian_id != '' ORDER BY guardian_name
            """).fetchall()
            types = connection.execute(
                "SELECT DISTINCT event_type FROM events ORDER BY event_type"
            ).fetchall()
        return {
            "guardians": [dict(row) for row in guardians],
            "event_types": [row[0] for row in types]
        }

    def export_events(self, filters, format_name):
        rows = self.query_events(**filters, page=1, per_page=100000)["rows"]
        if format_name == "json":
            return json.dumps(rows, indent=2, ensure_ascii=False)
        output = io.StringIO()
        fields = ["timestamp","event_type","level","status","guardian_id",
                  "guardian_name","message","response_time","old_status","new_status"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", delimiter=";")
        writer.writeheader(); writer.writerows(rows)
        return output.getvalue()

    def history(self, guardian_id, hours):
        since = (
            datetime.now() - timedelta(hours=max(1, hours))
        ).isoformat(timespec="seconds")

        if hours <= 24:
            bucket_seconds = 0
        elif hours <= 168:
            bucket_seconds = 300
        elif hours <= 720:
            bucket_seconds = 1800
        elif hours <= 2160:
            bucket_seconds = 3600
        elif hours <= 4320:
            bucket_seconds = 7200
        else:
            bucket_seconds = 14400

        with self.connect() as connection:
            rows = connection.execute("""
                SELECT timestamp,status,level,response_time,uptime
                FROM metrics
                WHERE guardian_id=? AND timestamp>=?
                ORDER BY timestamp
            """, (guardian_id, since)).fetchall()
            incident_rows = connection.execute("""
                SELECT id,status,severity,message,started_at,resolved_at,
                       acknowledged_at,acknowledged_by,acknowledge_note
                FROM incidents
                WHERE guardian_id=? AND (
                    started_at>=? OR acknowledged_at>=? OR resolved_at>=?
                    OR (started_at<? AND (resolved_at='' OR resolved_at>=?))
                    OR EXISTS (
                        SELECT 1
                        FROM incident_timeline AS timeline
                        WHERE timeline.incident_id=incidents.id
                          AND timeline.event_kind='note'
                          AND timeline.timestamp>=?
                    )
                )
                ORDER BY started_at DESC, id DESC
            """, (guardian_id, since, since, since, since, since, since)).fetchall()

            incident_ids = [int(row["id"]) for row in incident_rows]
            note_rows = []
            if incident_ids:
                placeholders = ",".join("?" for _ in incident_ids)
                note_rows = connection.execute(f"""
                    SELECT incident_id,timestamp,actor,message
                    FROM incident_timeline
                    WHERE event_kind='note'
                      AND incident_id IN ({placeholders})
                    ORDER BY timestamp,id
                """, incident_ids).fetchall()

        notes_by_incident = {}
        for row in note_rows:
            notes_by_incident.setdefault(int(row["incident_id"]), []).append({
                "timestamp": row["timestamp"],
                "actor": row["actor"],
                "message": row["message"],
            })

        raw_points = [dict(row) for row in rows]
        incidents = []
        for row in incident_rows:
            incident = dict(row)
            incident["acknowledged"] = bool(incident.get("acknowledged_at"))
            incident["notes"] = notes_by_incident.get(int(incident["id"]), [])
            incidents.append(incident)

        if bucket_seconds == 0:
            points = [
                {
                    "timestamp": point["timestamp"],
                    "timestamp_end": point["timestamp"],
                    "status": point["status"],
                    "level": point["level"],
                    "response_time": point["response_time"],
                    "response_time_min": point["response_time"],
                    "response_time_max": point["response_time"],
                    "uptime": point["uptime"],
                    "samples": 1,
                }
                for point in raw_points
            ]
        else:
            buckets = {}

            for point in raw_points:
                timestamp = datetime.fromisoformat(point["timestamp"])
                epoch = int(timestamp.timestamp())
                bucket_epoch = epoch - (epoch % bucket_seconds)

                if bucket_epoch not in buckets:
                    buckets[bucket_epoch] = {
                        "timestamp": datetime.fromtimestamp(
                            bucket_epoch
                        ).isoformat(timespec="seconds"),
                        "timestamp_end": datetime.fromtimestamp(
                            bucket_epoch + bucket_seconds
                        ).isoformat(timespec="seconds"),
                        "responses": [],
                        "uptimes": [],
                        "worst_level": 0,
                        "statuses": [],
                    }

                bucket = buckets[bucket_epoch]
                bucket["responses"].append(
                    int(point["response_time"] or 0)
                )
                bucket["uptimes"].append(float(point["uptime"] or 0))
                bucket["worst_level"] = max(
                    bucket["worst_level"],
                    int(point["level"] or 0),
                )
                bucket["statuses"].append(point["status"])

            points = []

            for bucket_epoch in sorted(buckets):
                bucket = buckets[bucket_epoch]
                responses = bucket["responses"]
                uptimes = bucket["uptimes"]
                worst_level = bucket["worst_level"]

                if worst_level >= 2:
                    status = "critical"
                elif worst_level == 1:
                    status = "warning"
                else:
                    status = "ok"

                points.append(
                    {
                        "timestamp": bucket["timestamp"],
                        "timestamp_end": bucket["timestamp_end"],
                        "status": status,
                        "level": worst_level,
                        "response_time": round(
                            sum(responses) / len(responses),
                            2,
                        ),
                        "response_time_min": min(responses),
                        "response_time_max": max(responses),
                        "uptime": round(
                            sum(uptimes) / len(uptimes),
                            2,
                        )
                        if uptimes
                        else 0,
                        "samples": len(responses),
                    }
                )

        total = len(raw_points)
        ok = sum(point["level"] == 0 for point in raw_points)
        warning = sum(point["level"] == 1 for point in raw_points)
        critical = sum(point["level"] >= 2 for point in raw_points)
        response = [
            int(point["response_time"] or 0)
            for point in raw_points
        ]

        return {
            "guardian_id": guardian_id,
            "hours": hours,
            "bucket_seconds": bucket_seconds,
            "points": points,
            "incidents": incidents,
            "summary": {
                "checks": total,
                "incidents": len(incidents),
                "acknowledged_incidents": sum(
                    1 for incident in incidents if incident["acknowledged"]
                ),
                "availability": round(ok / total * 100, 2)
                if total
                else 0,
                "ok": ok,
                "warning": warning,
                "critical": critical,
                "average_response_time": round(
                    sum(response) / len(response),
                    2,
                )
                if response
                else 0,
                "max_response_time": max(response)
                if response
                else 0,
            },
        }
