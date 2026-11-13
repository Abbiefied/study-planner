"""Data layer. One class, two backends: Postgres (production) or SQLite (local/dev/tests).

All SQL is portable between the two. Ids are random hex strings generated in Python.
Every write that touches personal data takes the acting username and filters on it,
so one person can never modify the other's rows even if the UI had a bug.
"""
import sqlite3
import threading
import uuid
import datetime as dt
from urllib.parse import quote, unquote

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
    "CREATE TABLE IF NOT EXISTS courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, sort DOUBLE PRECISION)",
    "CREATE TABLE IF NOT EXISTS comps (id TEXT PRIMARY KEY, course_id TEXT NOT NULL, name TEXT NOT NULL,"
    " ctype TEXT, weight DOUBLE PRECISION, sort DOUBLE PRECISION)",
    "CREATE TABLE IF NOT EXISTS grades (username TEXT NOT NULL, comp_id TEXT NOT NULL,"
    " grade DOUBLE PRECISION, whatif DOUBLE PRECISION, PRIMARY KEY (username, comp_id))",
    "CREATE TABLE IF NOT EXISTS targets (username TEXT NOT NULL, course_id TEXT NOT NULL,"
    " target DOUBLE PRECISION, PRIMARY KEY (username, course_id))",
    "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, username TEXT NOT NULL, day TEXT NOT NULL,"
    " course_id TEXT, kind TEXT, topic TEXT, status TEXT, done_at TEXT)",
    "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, username TEXT NOT NULL, day TEXT NOT NULL,"
    " minutes DOUBLE PRECISION, course_id TEXT, topic TEXT, created_at TEXT)",
]

DEFAULT_COMPONENTS = [
    ("Quiz 1", "quiz", 20), ("Quiz 2", "quiz", 20),
    ("Lab 1", "lab", 15), ("Lab 2", "lab", 15), ("Lab 3", "lab", 15), ("Lab 4", "lab", 15),
]


def normalize_url(url):
    """Tidy a pasted Postgres URL: trim spaces/quotes, accept postgres://, and percent-encode the password
    (a raw @ : / # ? in it would otherwise break the URL). Already-encoded passwords are left as they are."""
    url = (url or "").strip().strip("\"'")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if not url.startswith("postgresql://"):
        return url
    rest = url[len("postgresql://"):]
    if "@" not in rest:
        return url
    userinfo, hostpart = rest.rsplit("@", 1)
    if ":" not in userinfo:
        return url
    user, pw = userinfo.split(":", 1)
    return f"postgresql://{user}:{quote(unquote(pw), safe='')}@{hostpart}"


def _id():
    return uuid.uuid4().hex


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, url="sqlite:///study.db"):
        self.url = normalize_url(url) if not url.startswith("sqlite") else url
        self.pg = not url.startswith("sqlite")
        self.lock = threading.RLock()
        self.conn = None

    # ---------- plumbing ----------
    def _connect(self):
        if self.pg:
            import psycopg2
            return psycopg2.connect(self.url, connect_timeout=10)
        path = self.url.split("///", 1)[1] if "///" in self.url else self.url
        return sqlite3.connect(path, check_same_thread=False)

    def _run(self, sql, params=(), fetch=False):
        if self.pg:
            sql = sql.replace("?", "%s")
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.conn is None:
                        self.conn = self._connect()
                    cur = self.conn.cursor()
                    cur.execute(sql, params)
                    out = None
                    if fetch:
                        cols = [d[0] for d in cur.description]
                        out = [dict(zip(cols, r)) for r in cur.fetchall()]
                    self.conn.commit()
                    return out
                except Exception:
                    try:
                        if self.conn is not None:
                            self.conn.rollback()
                    except Exception:
                        pass
                    try:
                        if self.conn is not None:
                            self.conn.close()
                    except Exception:
                        pass
                    self.conn = None
                    if attempt == 2:
                        raise

    def init_schema(self):
        for stmt in SCHEMA:
            self._run(stmt)

    # ---------- shared: block settings, courses, components ----------
    def get_meta(self):
        return {r["k"]: r["v"] for r in self._run("SELECT k, v FROM meta", fetch=True)}

    def set_meta(self, key, value):
        if self._run("SELECT 1 AS x FROM meta WHERE k = ?", (key,), fetch=True):
            self._run("UPDATE meta SET v = ? WHERE k = ?", (value, key))
        else:
            self._run("INSERT INTO meta (k, v) VALUES (?, ?)", (key, value))

    def courses(self):
        return self._run("SELECT id, name, sort FROM courses ORDER BY sort, name", fetch=True)

    def comps(self):
        return self._run("SELECT id, course_id, name, ctype, weight, sort FROM comps ORDER BY sort, name", fetch=True)

    def add_course(self, name, with_defaults=True):
        cid = _id()
        n = len(self.courses())
        self._run("INSERT INTO courses (id, name, sort) VALUES (?, ?, ?)", (cid, name, n))
        if with_defaults:
            for i, (nm, ct, w) in enumerate(DEFAULT_COMPONENTS):
                self.add_comp(cid, nm, ct, w, sort=i)
        return cid

    def delete_course(self, course_id):
        for c in self._run("SELECT id FROM comps WHERE course_id = ?", (course_id,), fetch=True):
            self.delete_comp(c["id"])
        self._run("DELETE FROM targets WHERE course_id = ?", (course_id,))
        self._run("DELETE FROM courses WHERE id = ?", (course_id,))

    def add_comp(self, course_id, name, ctype, weight, sort=None):
        if sort is None:
            sort = len([c for c in self.comps() if c["course_id"] == course_id])
        cid = _id()
        self._run("INSERT INTO comps (id, course_id, name, ctype, weight, sort) VALUES (?, ?, ?, ?, ?, ?)",
                  (cid, course_id, name, ctype, float(weight or 0), sort))
        return cid

    def update_comp(self, comp_id, name, ctype, weight):
        self._run("UPDATE comps SET name = ?, ctype = ?, weight = ? WHERE id = ?",
                  (name, ctype, float(weight or 0), comp_id))

    def delete_comp(self, comp_id):
        self._run("DELETE FROM grades WHERE comp_id = ?", (comp_id,))
        self._run("DELETE FROM comps WHERE id = ?", (comp_id,))

    # ---------- personal: grades and targets ----------
    def grades(self, username):
        rows = self._run("SELECT comp_id, grade, whatif FROM grades WHERE username = ?", (username,), fetch=True)
        return {r["comp_id"]: (r["grade"], r["whatif"]) for r in rows}

    def set_grade(self, username, comp_id, grade, whatif):
        if self._run("SELECT 1 AS x FROM grades WHERE username = ? AND comp_id = ?", (username, comp_id), fetch=True):
            self._run("UPDATE grades SET grade = ?, whatif = ? WHERE username = ? AND comp_id = ?",
                      (grade, whatif, username, comp_id))
        else:
            self._run("INSERT INTO grades (username, comp_id, grade, whatif) VALUES (?, ?, ?, ?)",
                      (username, comp_id, grade, whatif))

    def targets(self, username):
        rows = self._run("SELECT course_id, target FROM targets WHERE username = ?", (username,), fetch=True)
        return {r["course_id"]: r["target"] for r in rows}

    def set_target(self, username, course_id, target):
        if self._run("SELECT 1 AS x FROM targets WHERE username = ? AND course_id = ?", (username, course_id), fetch=True):
            self._run("UPDATE targets SET target = ? WHERE username = ? AND course_id = ?", (target, username, course_id))
        else:
            self._run("INSERT INTO targets (username, course_id, target) VALUES (?, ?, ?)", (username, course_id, target))

    # ---------- personal: tasks ----------
    def tasks(self, username):
        return self._run("SELECT id, day, course_id, kind, topic, status, done_at FROM tasks"
                         " WHERE username = ? ORDER BY day, topic", (username,), fetch=True)

    def add_task(self, username, day, course_id, kind, topic):
        tid = _id()
        self._run("INSERT INTO tasks (id, username, day, course_id, kind, topic, status, done_at)"
                  " VALUES (?, ?, ?, ?, ?, ?, 'todo', NULL)", (tid, username, day, course_id, kind, topic))
        return tid

    def set_status(self, task_id, username, status):
        self._run("UPDATE tasks SET status = ?, done_at = ? WHERE id = ? AND username = ?",
                  (status, _now() if status == "done" else None, task_id, username))

    def delete_task(self, task_id, username):
        self._run("DELETE FROM tasks WHERE id = ? AND username = ?", (task_id, username))

    # ---------- personal: study sessions ----------
    def sessions(self, username):
        return self._run("SELECT id, day, minutes, course_id, topic, created_at FROM sessions"
                         " WHERE username = ? ORDER BY day DESC, created_at DESC", (username,), fetch=True)

    def add_session(self, username, day, minutes, course_id, topic):
        sid = _id()
        self._run("INSERT INTO sessions (id, username, day, minutes, course_id, topic, created_at)"
                  " VALUES (?, ?, ?, ?, ?, ?, ?)", (sid, username, day, float(minutes), course_id, topic, _now()))
        return sid

    def delete_session(self, session_id, username):
        self._run("DELETE FROM sessions WHERE id = ? AND username = ?", (session_id, username))

    # ---------- both people ----------
    def activity(self, usernames, limit=15):
        events = []
        for u in usernames:
            for s in self._run("SELECT minutes, course_id, topic, created_at FROM sessions WHERE username = ?",
                               (u,), fetch=True):
                events.append({"user": u, "at": s["created_at"] or "", "kind": "session", **s})
            for t in self._run("SELECT course_id, topic, done_at FROM tasks WHERE username = ? AND status = 'done'"
                               " AND done_at IS NOT NULL", (u,), fetch=True):
                events.append({"user": u, "at": t["done_at"], "kind": "task", **t})
        events.sort(key=lambda e: e["at"], reverse=True)
        return events[:limit]
