"""Smoke test: runs app.py top to bottom against a fake `streamlit`, on a temp SQLite DB.
It cannot check how the page looks, but it catches crashes, wrong variable names and bad store calls
in every tab, for an empty database, a populated one, and when viewing the buddy's read-only planner."""
import contextlib, datetime as dt, os, runpy, sys, tempfile, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Stop(Exception):
    pass


class Ctx:
    def __init__(self, st): self._st = st
    def __enter__(self): return self._st
    def __exit__(self, *a): return False
    def __getattr__(self, n): return getattr(self._st, n)


class FakeSt:
    def __init__(self, user, radio_idx):
        self.session_state = {"user": user} if user else {}
        self.radio_idx, self.calls = radio_idx, 0
        self.secrets = {}
        self.sidebar = Ctx(self)
        self.column_config = types.SimpleNamespace(**{k: (lambda *a, **k: None) for k in
                                                      ("SelectboxColumn", "NumberColumn")})
    def cache_resource(self, f): return f
    def stop(self): raise Stop()
    def rerun(self): raise Stop()
    def columns(self, spec, **k): return [Ctx(self) for _ in range(spec if isinstance(spec, int) else len(spec))]
    def tabs(self, labels): return [Ctx(self) for _ in labels]
    def expander(self, *a, **k): return Ctx(self)
    popover = expander
    def form(self, *a, **k): return Ctx(self)
    def radio(self, label, options, index=0, **k): return options[self.radio_idx if self.radio_idx is not None else index]
    def selectbox(self, label, options, index=0, **k): return options[index] if options else None
    def number_input(self, label, mn=None, mx=None, value=None, **k): return value
    def date_input(self, label, value=None, **k): return value
    def text_input(self, *a, **k): return ""
    def data_editor(self, df, **k): return df
    def __getattr__(self, name):
        if name in ("button", "form_submit_button", "checkbox"):
            return lambda *a, **k: False
        return lambda *a, **k: None


def run(user, radio_idx=None):
    fake = FakeSt(user, radio_idx)
    mod = types.ModuleType("streamlit"); mod.__dict__.update({n: getattr(fake, n) for n in dir(fake) if not n.startswith("__")})
    mod.__getattr__ = lambda n: getattr(fake, n)
    sys.modules["streamlit"] = mod
    for m in ("app", "calc", "store"): sys.modules.pop(m, None)
    try:
        runpy.run_path(os.path.join(ROOT, "app.py"))
    except Stop:
        pass


tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
os.environ.update({"DATABASE_URL": "sqlite:///" + tmp.name, "STUDY_DEV": "1"})

run(None); print("login screen ok")
run("me"); print("empty database ok")

from store import Store
s = Store("sqlite:///" + tmp.name); s.init_schema()
today = dt.date.today()
s.set_meta("block", "3"); s.set_meta("start", (today - dt.timedelta(days=3)).isoformat())
cid = s.add_course("DSCI 999")
comps = s.comps()
for u in ("me", "buddy"):
    s.set_grade(u, comps[0]["id"], 85.0, None); s.set_grade(u, comps[2]["id"], None, 90.0)
    s.set_target(u, cid, 85)
    t = s.add_task(u, today.isoformat(), cid, "Lab", "Lab 1"); s.set_status(t, u, "done")
    s.add_task(u, today.isoformat(), cid, "Study", "Recursion")
    s.add_session(u, today.isoformat(), 60, cid, "Trees")
run("me"); print("populated, my planner ok")
run("me", radio_idx=1); print("populated, buddy's planner (read-only) ok")
os.unlink(tmp.name)
print("ALL SMOKE RUNS PASSED")
