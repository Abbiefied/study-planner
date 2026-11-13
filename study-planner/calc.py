"""Pure functions (no Streamlit, no database): dates, weeks and grade maths."""
import datetime as dt


def to_date(s):
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(s)


def week_of(day, start):
    """Block week number (1-based) of `day`, or None when the block start date is not set."""
    if not start:
        return None
    return (to_date(day) - to_date(start)).days // 7 + 1


def clamp_week(w):
    return None if w is None else min(max(w, 1), 5)


def week_days(week, start, today):
    """The 7 ISO dates of a block week; the last 7 days when there is no start date."""
    if start and week:
        first = to_date(start) + dt.timedelta(days=(week - 1) * 7)
    else:
        first = to_date(today) - dt.timedelta(days=6)
    return [(first + dt.timedelta(days=i)).isoformat() for i in range(7)]


def course_stats(comps, grades, target=80.0):
    """comps: dicts with id and weight. grades: {comp_id: (grade, whatif)} (values may be None).

    current   = weighted average over graded items only
    projected = final % if every item without a grade uses its what-if (empty items count as 0)
    need      = average % required on the ungraded weight to reach `target`
    """
    total = graded = earned = proj = filled = 0.0
    for c in comps:
        w = float(c.get("weight") or 0)
        g, wi = grades.get(c["id"], (None, None))
        total += w
        if g is not None:
            graded += w
            earned += w * g / 100
        v = g if g is not None else wi
        if v is not None:
            filled += w
            proj += w * v / 100
    remaining = total - graded
    return {
        "total": total,
        "graded_weight": graded,
        "remaining": remaining,
        "current": earned / graded * 100 if graded else None,
        "projected": proj / total * 100 if total else None,
        "missing": total - filled,
        "need": ((target * total / 100) - earned) / remaining * 100 if remaining > 0 else None,
    }


def report_text(name, week, done, open_, hours, label):
    """Plain-text weekly report. `label(task)` renders one task line."""
    lines = [f"{name} week {week} report",
             f"Tasks: {len(done)}/{len(done) + len(open_)} completed",
             f"Study time: {hours:.1f} h", "", "Completed:"]
    lines += [f"- {label(t)}" for t in done] or ["- none"]
    lines += ["", "Not completed:"]
    lines += [f"- {label(t)}" for t in open_] or ["- none"]
    return "\n".join(lines)
