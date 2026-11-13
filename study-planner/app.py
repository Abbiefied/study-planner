"""MDS Block Study Planner: a shared study tracker for two accountability partners."""
import datetime as dt
import hmac
import os

import pandas as pd
import streamlit as st

import calc
from store import Store

st.set_page_config(page_title="MDS Block Study Planner", page_icon="📚", layout="wide")

KINDS = ["Study", "Lab", "Quiz prep", "Other"]
STATUS = {"todo": "To do", "doing": "In progress", "done": "Done"}
TYPES = ["quiz", "lab", "other"]


# ------------------------------------------------------------------ config
def secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name.upper(), default)


def load_users():
    try:
        users = {str(k): str(v) for k, v in dict(st.secrets["users"]).items()}
    except Exception:
        users = {}
    if not users and os.environ.get("STUDY_DEV") == "1":
        users = {"me": "dev", "buddy": "dev"}  # local development only
    return users


@st.cache_resource
def get_store():
    s = Store(secret("database_url", "sqlite:///study.db"))
    s.init_schema()
    return s


def today_date():
    tz = secret("timezone", "America/Vancouver")
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return dt.date.today()


USERS = load_users()
if not USERS:
    st.error("No users configured. Add a [users] section to the app secrets (see README.md).")
    st.stop()


def login_gate():
    if st.session_state.get("user") in USERS:
        return st.session_state["user"]
    st.title("📚 MDS Block Study Planner")
    with st.form("login"):
        name = st.selectbox("Who are you?", list(USERS))
        pin = st.text_input("Password", type="password")
        ok = st.form_submit_button("Log in")
    if ok:
        if hmac.compare_digest(pin.encode(), USERS[name].encode()):
            st.session_state["user"] = name
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


ME = login_gate()
try:
    store = get_store()
except Exception as exc:  # Streamlit hides uncaught error text, so show a safe version
    msg = " ".join(str(exc).split())
    st.error(f"Could not connect to the database ({type(exc).__name__}): {msg[:400]}")
    low = msg.lower()
    if "unreachable" in low or "ipv6" in low or "could not translate host" in low or "name or service" in low:
        st.info("This looks like a network/host problem. With Supabase, use the **Session pooler** connection string "
                "(host like aws-0-<region>.pooler.supabase.com, user `postgres.<project-ref>`), not the direct "
                "`db.<ref>.supabase.co` one: Streamlit Cloud has no IPv6.")
    elif "password" in low or "authentication" in low or "tenant or user not found" in low:
        st.info("This looks like a login problem. Check the database password and, for the pooler, that the user is "
                "`postgres.<project-ref>` (with the dot and your project ref).")
    st.stop()
PEOPLE = list(USERS)

# ------------------------------------------------------------------ sidebar / who am I viewing
with st.sidebar:
    st.write(f"Logged in as **{ME}**")
    VIEW = st.radio("Viewing", PEOPLE, index=PEOPLE.index(ME),
                    format_func=lambda p: "My planner" if p == ME else f"{p}’s planner")
    if st.button("Log out"):
        st.session_state.pop("user", None)
        st.rerun()
RO = VIEW != ME

# ------------------------------------------------------------------ data
TODAY = today_date()
meta = store.get_meta()
START = meta.get("start") or None
BLOCK = meta.get("block", "3")
COURSES = store.courses()
COMPS = store.comps()
CN = {c["id"]: c["name"] for c in COURSES}
DATA = {p: {"tasks": store.tasks(p), "sessions": store.sessions(p),
            "grades": store.grades(p), "targets": store.targets(p)} for p in PEOPLE}
WEEK = calc.clamp_week(calc.week_of(TODAY, START))
WEEK_DAYS = calc.week_days(WEEK, START, TODAY)


def poss(p):
    return "Your" if p == ME else f"{p}’s"


def cname(cid):
    return CN.get(cid, "(removed course)")


def minutes_on(p, day):
    return sum(s["minutes"] or 0 for s in DATA[p]["sessions"] if s["day"] == day)


def week_tasks(p, week, days):
    if week is None:
        return [t for t in DATA[p]["tasks"] if t["day"] in days]
    return [t for t in DATA[p]["tasks"] if calc.week_of(t["day"], START) == week]


def nn(v):
    return None if v is None or pd.isna(v) else float(v)


def course_options():
    return [c["id"] for c in COURSES]


# ------------------------------------------------------------------ header
st.title(f"Block {BLOCK} Study Planner")
st.caption((f"Week {WEEK} of 5 · " if WEEK else "Set the block start date on the Dashboard · ")
           + f"today is {TODAY:%a %b %d}")
if RO:
    st.info(f"👀 You’re viewing {VIEW}’s planner. It’s read-only; pick “My planner” in the sidebar to make changes.")

tab_dash, tab_tasks, tab_grades, tab_log, tab_report = st.tabs(
    ["Dashboard", "Daily plan", "Grades", "Study log", "Weekly report"])


# ------------------------------------------------------------------ dashboard
with tab_dash:
    st.subheader("This week: you vs. your buddy")
    cols = st.columns(len(PEOPLE))
    for col, p in zip(cols, PEOPLE):
        wk = week_tasks(p, WEEK, WEEK_DAYS)
        done = sum(1 for t in wk if t["status"] == "done")
        mins = sum(minutes_on(p, d) for d in WEEK_DAYS)
        studied = sum(1 for d in WEEK_DAYS if minutes_on(p, d) > 0)
        with col:
            st.markdown(f"**{'You' if p == ME else p}**")
            st.progress(done / len(wk) if wk else 0.0, text=f"{done}/{len(wk)} tasks done")
            st.caption(f"{mins / 60:.1f} h studied · studied on {studied} of 7 days")

    st.subheader("Study minutes per day")
    chart = pd.DataFrame({("You" if p == ME else p): [minutes_on(p, d) for d in WEEK_DAYS] for p in PEOPLE},
                         index=[d[5:] for d in WEEK_DAYS])
    st.bar_chart(chart)

    st.subheader(f"{poss(VIEW)} projected final by course")
    if not COURSES:
        st.caption("Add courses in the Grades tab to see projections.")
    for c in COURSES:
        cs = [x for x in COMPS if x["course_id"] == c["id"]]
        tgt = DATA[VIEW]["targets"].get(c["id"], 80.0)
        stt = calc.course_stats(cs, DATA[VIEW]["grades"], tgt)
        proj = stt["projected"]
        st.progress(min(max((proj or 0) / 100, 0.0), 1.0),
                    text=f"{c['name']}: projected {proj:.1f}% (target {tgt:.0f}%)" if proj is not None
                    else f"{c['name']}: no weights yet")

    st.subheader("Recent activity (both of you)")
    feed = store.activity(PEOPLE)
    if not feed:
        st.caption("Nothing logged yet.")
    for e in feed:
        who = "You" if e["user"] == ME else e["user"]
        when = e["at"][:10]
        if e["kind"] == "session":
            st.write(f"**{who}** studied {cname(e['course_id'])} for {e['minutes']:.0f} min ({e['topic']}) · {when}")
        else:
            st.write(f"**{who}** finished {cname(e['course_id'])}: {e['topic']} · {when}")

    with st.expander("Block settings (shared)"):
        with st.form("meta"):
            b = st.number_input("Block number", 1, 6, int(BLOCK) if str(BLOCK).isdigit() else 3)
            s = st.date_input("Week 1 starts on", value=dt.date.fromisoformat(START) if START else TODAY)
            if st.form_submit_button("Save", disabled=RO):
                store.set_meta("block", str(int(b)))
                store.set_meta("start", s.isoformat())
                st.rerun()
        st.caption("Weeks 1–2 lectures · week 3 lectures + Quiz 1 · week 4 lectures · week 5 Quiz 2. One lab each week.")


# ------------------------------------------------------------------ daily plan
def cb_status(task_id):
    store.set_status(task_id, ME, st.session_state[f"status_{task_id}"])


def cb_delete_task(task_id):
    store.delete_task(task_id, ME)


with tab_tasks:
    sel = st.date_input("Day", value=TODAY, key="sel_day")
    monday = sel - dt.timedelta(days=sel.weekday())
    strip = st.columns(7)
    for i, col in enumerate(strip):
        d = monday + dt.timedelta(days=i)
        day_tasks = [t for t in DATA[VIEW]["tasks"] if t["day"] == d.isoformat()]
        col.metric(f"{d:%a %d}", f"{sum(t['status'] == 'done' for t in day_tasks)}/{len(day_tasks)}")

    wk_no = calc.week_of(sel, START)
    st.subheader(f"{poss(VIEW)} plan for {sel:%A %b %d}" + (f" · week {wk_no}" if wk_no else ""))
    todays = [t for t in DATA[VIEW]["tasks"] if t["day"] == sel.isoformat()]
    if not todays:
        st.caption("Nothing planned for this day.")
    for t in todays:
        c1, c2, c3 = st.columns([5, 2, 1])
        c1.markdown(f"**{cname(t['course_id'])}** · {t['topic']} · `{t['kind']}`")
        c2.selectbox("Status", list(STATUS), index=list(STATUS).index(t["status"] or "todo"),
                     format_func=STATUS.get, key=f"status_{t['id']}", label_visibility="collapsed",
                     disabled=RO, on_change=cb_status, args=(t["id"],))
        c3.button("🗑", key=f"deltask_{t['id']}", disabled=RO, on_click=cb_delete_task, args=(t["id"],))

    if not RO:
        st.divider()
        if not COURSES:
            st.caption("Add a course in the Grades tab first.")
        else:
            with st.form("add_task", clear_on_submit=True):
                st.markdown(f"**Add a task for {sel:%b %d}**")
                f1, f2 = st.columns(2)
                course = f1.selectbox("Course", course_options(), format_func=cname)
                kind = f2.selectbox("Type", KINDS)
                topic = st.text_input("Topic or lab", placeholder="e.g. Lab 3 q1–q4")
                if st.form_submit_button("Add task") and topic.strip():
                    store.add_task(ME, sel.isoformat(), course, kind, topic.strip())
                    st.rerun()


# ------------------------------------------------------------------ grades
with tab_grades:
    if not RO:
        with st.form("add_course", clear_on_submit=True):
            n = st.text_input("New course name", placeholder="e.g. DSCI 5xx")
            if st.form_submit_button("Add course") and n.strip():
                store.add_course(n.strip())
                st.rerun()
        st.caption("Courses and weights are shared by both of you; grades and targets are personal. "
                   "New courses start with Quiz 1, Quiz 2 and Labs 1–4 using placeholder weights: edit them to match "
                   "the syllabus and add extras (iClicker, oral check-in…).")
    if not COURSES:
        st.info("No courses yet.")

    for c in COURSES:
        cid = c["id"]
        cs = [x for x in COMPS if x["course_id"] == cid]
        with st.expander(c["name"], expanded=True):
            target = DATA[VIEW]["targets"].get(cid, 80.0)
            new_t = st.number_input("Target %", 0.0, 100.0, float(target), key=f"target_{cid}", disabled=RO)
            if not RO and new_t != target:
                store.set_target(ME, cid, new_t)
                DATA[VIEW]["targets"][cid] = new_t
                target = new_t
            stt = calc.course_stats(cs, DATA[VIEW]["grades"], target)
            m1, m2, m3 = st.columns(3)
            m1.metric("Current (graded only)", "–" if stt["current"] is None else f"{stt['current']:.1f}%",
                      f"{stt['graded_weight']:g}% of weight graded", delta_color="off")
            m2.metric("Projected final", "–" if stt["projected"] is None else f"{stt['projected']:.1f}%",
                      f"{stt['missing']:g}% empty (counts as 0)" if stt["missing"] > 0 else "all items filled",
                      delta_color="off")
            m3.metric(f"Average needed for {target:.0f}%", "–" if stt["need"] is None else f"{stt['need']:.1f}%",
                      f"on the {stt['remaining']:g}% left" if stt["remaining"] > 0 else "nothing left to earn",
                      delta_color="off")
            if abs(stt["total"] - 100) > 0.01:
                st.warning(f"Weights add up to {stt['total']:g}%, not 100%.")

            g = DATA[VIEW]["grades"]
            df = pd.DataFrame(
                [{"id": x["id"], "Item": x["name"], "Type": x["ctype"] or "other", "Weight %": x["weight"],
                  "Grade %": (g.get(x["id"]) or (None, None))[0], "What-if %": (g.get(x["id"]) or (None, None))[1]}
                 for x in cs],
                columns=["id", "Item", "Type", "Weight %", "Grade %", "What-if %"])
            for col in ("Weight %", "Grade %", "What-if %"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.set_index("id")
            edited = st.data_editor(
                df, key=f"editor_{cid}", hide_index=True, disabled=RO, use_container_width=True,
                column_config={
                    "Type": st.column_config.SelectboxColumn(options=TYPES, required=True),
                    "Weight %": st.column_config.NumberColumn(min_value=0, max_value=100),
                    "Grade %": st.column_config.NumberColumn(min_value=0, max_value=200),
                    "What-if %": st.column_config.NumberColumn(min_value=0, max_value=200,
                                                                help="Ignored once a real grade is entered"),
                })
            if not RO and st.button("Save changes", key=f"save_{cid}", type="primary"):
                for idx, row in edited.iterrows():
                    old = df.loc[idx]
                    if (row["Item"], row["Type"], nn(row["Weight %"])) != (old["Item"], old["Type"], nn(old["Weight %"])):
                        store.update_comp(idx, str(row["Item"]), row["Type"], nn(row["Weight %"]) or 0)
                    if (nn(row["Grade %"]), nn(row["What-if %"])) != (nn(old["Grade %"]), nn(old["What-if %"])):
                        store.set_grade(ME, idx, nn(row["Grade %"]), nn(row["What-if %"]))
                st.rerun()

            if not RO:
                with st.popover("Add or remove items"):
                    with st.form(f"add_comp_{cid}", clear_on_submit=True):
                        a1, a2, a3 = st.columns([3, 2, 2])
                        nm = a1.text_input("Item", placeholder="iClicker, oral check-in…")
                        ty = a2.selectbox("Type", TYPES, index=2)
                        wt = a3.number_input("Weight %", 0.0, 100.0, 0.0)
                        if st.form_submit_button("Add item") and nm.strip():
                            store.add_comp(cid, nm.strip(), ty, wt)
                            st.rerun()
                    if cs:
                        rm = st.selectbox("Remove item", [x["id"] for x in cs],
                                          format_func=lambda i: next(x["name"] for x in cs if x["id"] == i),
                                          key=f"rm_{cid}")
                        if st.button("Remove item", key=f"rmbtn_{cid}"):
                            store.delete_comp(rm)
                            st.rerun()
                    st.divider()
                    sure = st.checkbox("I want to delete this whole course (for both of us)", key=f"sure_{cid}")
                    if st.button("Delete course", key=f"delc_{cid}", disabled=not sure):
                        store.delete_course(cid)
                        st.rerun()


# ------------------------------------------------------------------ study log
def cb_delete_session(session_id):
    store.delete_session(session_id, ME)


with tab_log:
    if not RO:
        if not COURSES:
            st.caption("Add a course first.")
        else:
            with st.form("add_session", clear_on_submit=True):
                st.markdown("**Log a study session**")
                l1, l2, l3 = st.columns(3)
                day = l1.date_input("Day", value=TODAY)
                mins = l2.number_input("Minutes", 5, 600, 45, step=5)
                course = l3.selectbox("Course", course_options(), format_func=cname)
                topic = st.text_input("What did you study?")
                if st.form_submit_button("Log session"):
                    store.add_session(ME, day.isoformat(), mins, course, topic.strip() or "Study session")
                    st.rerun()
    st.subheader(f"{poss(VIEW)} recent sessions")
    sess = DATA[VIEW]["sessions"][:40]
    if not sess:
        st.caption("No sessions logged yet.")
    for s in sess:
        c1, c2 = st.columns([8, 1])
        c1.write(f"{s['day']} · **{cname(s['course_id'])}** · {s['topic']} · **{s['minutes']:.0f} min**")
        c2.button("🗑", key=f"delsess_{s['id']}", disabled=RO, on_click=cb_delete_session, args=(s["id"],))


# ------------------------------------------------------------------ weekly report
with tab_report:
    w = st.selectbox("Week", [1, 2, 3, 4, 5], index=(WEEK or 1) - 1)
    days = calc.week_days(w, START, TODAY)
    wk = week_tasks(VIEW, w, days)
    done = [t for t in wk if t["status"] == "done"]
    open_ = [t for t in wk if t["status"] != "done"]
    sess_w = [s for s in DATA[VIEW]["sessions"] if s["day"] in days]
    hours = sum(s["minutes"] or 0 for s in sess_w) / 60

    def label(t):
        return f"{t['day'][5:]} {cname(t['course_id'])}: {t['topic']} [{t['kind']}]" + \
               (" (in progress)" if t["status"] == "doing" else "")

    st.subheader(f"{poss(VIEW)} week {w}")
    r1, r2, r3 = st.columns(3)
    r1.metric("Done", len(done))
    r2.metric("Not done", len(open_))
    r3.metric("Hours studied", f"{hours:.1f}")
    st.progress(len(done) / len(wk) if wk else 0.0)
    a, b = st.columns(2)
    with a:
        st.markdown("**Completed**")
        for t in done:
            st.write("✅ " + label(t))
        if not done:
            st.caption("None yet.")
    with b:
        st.markdown("**Not completed**")
        for t in open_:
            st.write("⬜ " + label(t))
        if not open_:
            st.caption("Everything done 🎉")
    if COURSES:
        st.markdown("**Minutes by course**")
        by = pd.DataFrame({"minutes": [sum(s["minutes"] or 0 for s in sess_w if s["course_id"] == c["id"])
                                       for c in COURSES]}, index=[c["name"] for c in COURSES])
        st.bar_chart(by)
    st.markdown("**Plain-text version** (use the copy icon):")
    st.code(calc.report_text("My" if VIEW == ME else poss(VIEW), w, done, open_, hours, label), language=None)
