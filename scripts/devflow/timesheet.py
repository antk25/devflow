import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RULES_PATH = Path.home() / '.config' / 'devflow' / 'timesheet.json'
STATE_DIR = Path.home() / '.claude' / 'devflow' / 'timesheet'
INTEGRATIONS = Path(__file__).resolve().parents[2] / 'integrations'
MSK = timezone(timedelta(hours=3))
MODES = ('per-issue', 'bucket')
WEEKDAYS = ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс')
QUARTER = 900
BLOCK_GAP = timedelta(minutes=15)


class RulesError(ValueError):
    pass


class JiraError(RuntimeError):
    pass


@dataclass
class Sheet:
    name: str
    account: str
    author: str
    day_hours: float
    week_hours: float


@dataclass
class ProjectRule:
    project: str
    sheet: str
    mode: str
    jira_project: str
    issue: str = ''
    manual: list = field(default_factory=list)
    mirror_prefix: str = ''
    mirrors: dict = field(default_factory=dict)
    comment: str = ''

    def owns(self, key: str) -> bool:
        if self.mode == 'bucket':
            return key == self.issue
        return key.split('-')[0] == self.jira_project


@dataclass
class Rules:
    sheets: dict
    projects: list

    def project_of(self, sheet: str, key: str) -> str | None:
        return next((p.project for p in self.projects if p.sheet == sheet and p.owns(key)), None)


@dataclass
class Worklog:
    sheet: str
    key: str
    day: date
    seconds: int
    comment: str = ''
    id: str = ''
    author: str = ''


@dataclass
class Unavailable:
    reason: str


@dataclass
class DraftLine:
    sheet: str
    day: date
    key: str
    seconds: int
    comment: str = ''
    source: str = 'activity'
    flags: list = field(default_factory=list)
    sent_id: str = ''


def _positive(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RulesError(f'{where}: норма должна быть числом больше нуля, получено {value!r}')
    return float(value)


def load_rules(path: Path, accounts: set) -> Rules:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RulesError(f'{path}: {e}') from e
    sheets = {}
    for name, s in (raw.get('sheets') or {}).items():
        if s.get('account') not in accounts:
            raise RulesError(f'{name}.account: неизвестный аккаунт {s.get("account")!r}, есть: {", ".join(sorted(accounts))}')
        if not s.get('author'):
            raise RulesError(f'{name}.author: нужен accountId автора ворклогов')
        sheets[name] = Sheet(name, s['account'], s['author'],
                             _positive(s.get('day_hours'), f'{name}.day_hours'),
                             _positive(s.get('week_hours'), f'{name}.week_hours'))
    if not sheets:
        raise RulesError(f'{path}: нет ни одного табеля в sheets')
    projects = []
    for proj, per_sheet in (raw.get('projects') or {}).items():
        for sheet, r in per_sheet.items():
            if sheet not in sheets:
                raise RulesError(f'{proj}.{sheet}: неизвестный табель, есть: {", ".join(sheets)}')
            mode = r.get('mode', 'per-issue')
            if mode not in MODES:
                raise RulesError(f'{proj}.{sheet}.mode: {mode!r}, допустимо: {", ".join(MODES)}')
            issue = r.get('issue', '')
            jira_project = r.get('jira_project') or issue.split('-')[0]
            if mode == 'bucket' and not issue:
                raise RulesError(f'{proj}.{sheet}.issue: режим bucket требует задачу')
            if not jira_project:
                raise RulesError(f'{proj}.{sheet}.jira_project: не задан ключ проекта Jira')
            projects.append(ProjectRule(proj, sheet, mode, jira_project, issue, list(r.get('manual', [])),
                                        r.get('mirror_prefix', ''), dict(r.get('mirrors', {})), r.get('comment', '')))
    return Rules(sheets, projects)


def msk_day(started: str) -> date:
    return datetime.strptime(started, '%Y-%m-%dT%H:%M:%S.%f%z' if '.' in started else '%Y-%m-%dT%H:%M:%S%z') \
        .astimezone(MSK).date()


def week_range(week: str, today: date | None = None) -> tuple:
    w = week.upper()
    year = (today or date.today()).isocalendar()[0]
    if '-W' in w:
        year, w = int(w.split('-W')[0]), w.split('-W')[1]
    num = int(w.lstrip('W'))
    monday = date.fromisocalendar(year, num, 1)
    return monday, monday + timedelta(days=6)


def current_week(today: date | None = None) -> str:
    y, w, _ = (today or date.today()).isocalendar()
    return f'{y}-W{w:02d}'


def jira(script: str, *args: str) -> list:
    cmd = [str(INTEGRATIONS / script), *args]
    for attempt in (1, 2):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise JiraError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f'{script}: код {proc.returncode}')
        try:
            out = proc.stdout.strip()
            if script == 'jira-jql.sh':
                return [json.loads(line) for line in out.splitlines() if line.strip()]
            return [json.loads(out)]
        except json.JSONDecodeError:
            if attempt == 2:
                raise JiraError(f'{script}: ответ не JSON')
    return []


def accounts_available() -> set:
    proc = subprocess.run(['bash', '-c', f'source "{INTEGRATIONS}/jira-accounts.sh"; jira_accounts_load; jira_accounts_list'],
                          capture_output=True, text=True)
    return set(proc.stdout.split())


def _epoch_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=MSK).timestamp() * 1000)


def fetch_sheet(sheet: Sheet, start: date, end: date, call=jira) -> list:
    lo, hi = start - timedelta(days=1), end + timedelta(days=1)
    jql = f'worklogAuthor = currentUser() AND worklogDate >= "{lo}" AND worklogDate <= "{hi}"'
    issues = call('jira-jql.sh', '--account', sheet.account, jql, 'summary', '1000')
    out = []
    for issue in issues:
        key, at = issue['key'], 0
        while True:
            query = f'startedAfter={_epoch_ms(lo)}&startedBefore={_epoch_ms(hi + timedelta(days=1))}&startAt={at}&maxResults=1000'
            page = call('jira-raw.sh', f'{key}/worklog', '.', query)[0]
            logs = page.get('worklogs', [])
            for w in logs:
                day = msk_day(w['started'])
                author = (w.get('author') or {}).get('accountId', '')
                if author == sheet.author and start <= day <= end:
                    out.append(Worklog(sheet.name, key, day, int(w['timeSpentSeconds']),
                                       _comment_text(w.get('comment')), str(w.get('id', '')), author))
            at += len(logs)
            if not logs or at >= page.get('total', 0):
                break
    return out


def _comment_text(c) -> str:
    if isinstance(c, str) or c is None:
        return c or ''
    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get('type') == 'text':
                parts.append(node.get('text', ''))
            for child in node.get('content', []):
                walk(child)
    walk(c)
    return ''.join(parts)


def fetch_worklogs(rules: Rules, week: str, call=jira) -> dict:
    start, end = week_range(week)
    result = {}
    for name, sheet in rules.sheets.items():
        try:
            result[name] = fetch_sheet(sheet, start, end, call)
        except JiraError as e:
            result[name] = Unavailable(str(e))
    return result


def summary(rules: Rules, worklogs: dict, week: str) -> dict:
    start, end = week_range(week)
    days = [start + timedelta(days=i) for i in range(7)]
    out = {}
    for name, sheet in rules.sheets.items():
        logs = worklogs.get(name)
        if isinstance(logs, Unavailable) or logs is None:
            out[name] = {'unavailable': logs.reason if logs else 'нет данных'}
            continue
        by_day, by_project = defaultdict(int), defaultdict(int)
        by_issue = defaultdict(lambda: defaultdict(int))
        for w in logs:
            project = rules.project_of(name, w.key)
            if project is None:
                continue
            by_day[w.day] += w.seconds
            by_project[project] += w.seconds
            by_issue[project][w.key] += w.seconds
        out[name] = {
            'account': sheet.account,
            'norm_day': sheet.day_hours * 3600,
            'norm_week': sheet.week_hours * 3600,
            'total': sum(by_day.values()),
            'days': {d: by_day.get(d, 0) for d in days},
            'empty': [d for d in days if d.weekday() < 5 and not by_day.get(d)],
            'projects': dict(by_project),
            'issues': {p: dict(v) for p, v in by_issue.items()},
        }
    return out


def hours(seconds: float) -> str:
    return f'{seconds / 3600:.1f}'.replace('.', ',')


def render(s: dict, week: str) -> str:
    start, end = week_range(week)
    lines = [f'Неделя {week}: {start} — {end}']
    for name, data in s.items():
        lines.append('')
        if 'unavailable' in data:
            lines.append(f'{name}: нет доступа ({data["unavailable"]})')
            continue
        lines.append(f'{name} ({data["account"]}): {hours(data["total"])} / {hours(data["norm_week"])} ч')
        for d, sec in data['days'].items():
            if d.weekday() < 5 or sec:
                mark = ' — пусто' if d in data['empty'] else ''
                lines.append(f'  {WEEKDAYS[d.weekday()]} {d:%d.%m}  {hours(sec):>5} / {hours(data["norm_day"])}{mark}')
        for project, sec in sorted(data['projects'].items(), key=lambda kv: -kv[1]):
            lines.append(f'  {project}: {hours(sec)}')
            for key, isec in sorted(data['issues'][project].items(), key=lambda kv: -kv[1]):
                lines.append(f'    {key:<10} {isec / 3600:6.2f}'.replace('.', ','))
    return '\n'.join(lines)


def key_pattern(rules: Rules) -> re.Pattern:
    prefixes = sorted({p for r in rules.projects for p in (r.jira_project, r.mirror_prefix) if p})
    return re.compile(rf"\b(?:{'|'.join(prefixes)})-\d{{1,5}}\b", re.I)


def rule_project(rules: Rules, cwd: str) -> str | None:
    from devflow.transcripts import project_of
    names = {r.project for r in rules.projects}
    return next((seg for seg in project_of(cwd).split('/') if seg in names), None)


def tagged_messages(rules: Rules, msgs, ledger: dict, since: datetime) -> list:
    """(ts, project, key) по сообщениям с ts >= since; более ранние дают только метки задач."""
    from devflow.transcripts import NO_TASK, assign_tasks
    key_re = key_pattern(rules)
    by_session = defaultdict(list)
    for m in msgs:
        by_session[m.session].append(m)
    out = []
    for sid, items in by_session.items():
        marks = list(ledger.get(sid, []))
        marks += [(m.ts, k.group(0).upper()) for m in items for k in key_re.finditer(m.text[:8000])]
        rows = [{'ts': m.ts, 'cwd': m.cwd} for m in items]
        assign_tasks(rows, marks)
        for r in rows:
            project = rule_project(rules, r['cwd'])
            if project and r['ts'] >= since:
                out.append((r['ts'], project, '' if r['task'] == NO_TASK else r['task']))
    return out


def activity(rules: Rules, msgs: list, week: str) -> dict:
    """msgs — (ts, project, key); сб и вс прошлой недели уходят в этот понедельник."""
    start, end = week_range(week)
    out = defaultdict(lambda: defaultdict(int))
    ordered = sorted(msgs, key=lambda m: m[0])
    for i, (ts, project, key) in enumerate(ordered):
        gap = ordered[i + 1][0] - ts if i + 1 < len(ordered) else None
        spent = gap if gap is not None and gap <= BLOCK_GAP else BLOCK_GAP / 2
        day = ts.astimezone(MSK).date()
        if day.weekday() >= 5:
            day += timedelta(days=7 - day.weekday())
        if start <= day <= end:
            out[day][(project, key)] += int(spent.total_seconds())
    return {d: dict(v) for d, v in out.items()}


def round_quarters(parts: dict, total: int) -> dict:
    weights = {k: v for k, v in parts.items() if v > 0}
    if not weights or total <= 0:
        return {}
    whole = sum(weights.values())
    units = total // QUARTER
    raw = {k: units * v / whole for k, v in weights.items()}
    got = {k: int(x) for k, x in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - got[k]), -weights[k]))[:units - sum(got.values())]:
        got[k] += 1
    out = {k: n * QUARTER for k, n in got.items()}
    out[max(weights, key=weights.get)] += total - units * QUARTER
    return {k: v for k, v in out.items() if v > 0}


def _manual_lines(manual: list, sheet: str, day: date, logged: list) -> list:
    lines = []
    for m in manual:
        if m['sheet'] != sheet or date.fromisoformat(str(m['day'])) != day:
            continue
        sent = next((w for w in logged if w.key == m['key'] and w.seconds == int(m['seconds'])), None)
        lines.append(DraftLine(sheet, day, m['key'], int(m['seconds']), m.get('comment', ''), 'manual',
                               sent_id=sent.id if sent else ''))
    return lines


def draft_client(rules: Rules, worklogs: dict, act: dict, manual: list, week: str, sheet: str = 'client') -> list:
    start, _ = week_range(week)
    norm = int(rules.sheets[sheet].day_hours * 3600)
    logs = worklogs.get(sheet)
    if isinstance(logs, Unavailable) or logs is None:
        return []
    owned = [r for r in rules.projects if r.sheet == sheet and r.mode == 'per-issue']
    out = []
    for day in (start + timedelta(days=i) for i in range(5)):
        logged = [w for w in logs if w.day == day and rules.project_of(sheet, w.key)]
        manual_lines = _manual_lines(manual, sheet, day, logged)
        out += manual_lines
        manual_sec = sum(m.seconds for m in manual_lines if not m.sent_id)
        remaining = norm - manual_sec - sum(w.seconds for w in logged)
        if remaining <= 0:
            continue
        manual_keys = {k for r in owned for k in r.manual} | {m.key for m in manual_lines}
        weights = defaultdict(int)
        for (project, key), sec in act.get(day, {}).items():
            if key and key not in manual_keys and any(r.project == project and r.owns(key) for r in owned):
                weights[key] += sec
        if not weights:
            out.append(DraftLine(sheet, day, '', 0, flags=['empty-day']))
            continue
        per_key_logged = defaultdict(int)
        for w in logged:
            per_key_logged[w.key] += w.seconds
        ideal = round_quarters(weights, norm - manual_sec - sum(v for k, v in per_key_logged.items() if k in manual_keys))
        need = {k: max(0, v - per_key_logged[k]) for k, v in ideal.items()}
        for key, sec in sorted(round_quarters(need if any(need.values()) else weights, remaining).items(),
                               key=lambda kv: -kv[1]):
            out.append(DraftLine(sheet, day, key, sec))
    return out


def load_manual(week: str, state: Path = STATE_DIR) -> list:
    path = state / f'manual-{week}.json'
    return json.loads(path.read_text()) if path.exists() else []


def save_manual(week: str, items: list, state: Path = STATE_DIR) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / f'manual-{week}.json').write_text(json.dumps(items, ensure_ascii=False, indent=1))


def save_draft(week: str, lines: list, state: Path = STATE_DIR) -> Path:
    state.mkdir(parents=True, exist_ok=True)
    path = state / f'draft-{week}.json'
    rows = [{**asdict(line), 'day': line.day.isoformat()} for line in lines]
    path.write_text(json.dumps({'week': week, 'generated': datetime.now(MSK).isoformat(timespec='seconds'),
                                'lines': rows}, ensure_ascii=False, indent=1))
    return path


def load_activity(rules: Rules, week: str) -> dict:
    from devflow.transcripts import PROJECTS_ROOT, human_messages, load_ledger
    start, end = week_range(week)
    count_from = datetime(start.year, start.month, start.day, tzinfo=MSK) - timedelta(days=2)
    until = datetime(end.year, end.month, end.day, tzinfo=MSK) - timedelta(days=1)
    msgs = list(human_messages(PROJECTS_ROOT, count_from - timedelta(days=7), until))
    return activity(rules, tagged_messages(rules, msgs, load_ledger(), count_from), week)


def render_draft(lines: list, week: str) -> str:
    out = [f'Черновик {week}']
    for line in lines:
        head = f'  {line.sheet:<8} {WEEKDAYS[line.day.weekday()]} {line.day:%d.%m}'
        if 'empty-day' in line.flags:
            out.append(f'{head}  — пустой день, активности нет')
            continue
        tail = ' [ручная]' if line.source == 'manual' else ''
        tail += ' [уже в Jira]' if line.sent_id else ''
        amount = f'{line.seconds / 3600:5.2f}'.replace('.', ',')
        out.append(f'{head}  {line.key:<10} {amount}{tail}{"  " + line.comment if line.comment else ""}')
    if len(out) == 1:
        out.append('  предлагать нечего: все будние дни добраны')
    return '\n'.join(out)


def _load(args):
    week = args.week or current_week()
    return week, load_rules(args.rules, accounts_available())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='timesheet')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('summary', 'draft'):
        p = sub.add_parser(name)
        p.add_argument('--week', default=None)
        p.add_argument('--rules', type=Path, default=RULES_PATH)
    m = sub.add_parser('manual')
    msub = m.add_subparsers(dest='action', required=True)
    add = msub.add_parser('add')
    add.add_argument('--sheet', required=True)
    add.add_argument('--day', required=True, type=date.fromisoformat)
    add.add_argument('--key', required=True)
    add.add_argument('--hours', required=True, type=float)
    add.add_argument('--comment', default='')
    rm = msub.add_parser('rm')
    rm.add_argument('--week', required=True)
    rm.add_argument('index', type=int)
    ls = msub.add_parser('list')
    ls.add_argument('--week', default=None)
    args = ap.parse_args(argv)

    if args.cmd == 'manual':
        if args.action == 'add':
            week = current_week(args.day)
            items = load_manual(week)
            items.append({'sheet': args.sheet, 'day': args.day.isoformat(), 'key': args.key.upper(),
                          'seconds': round(args.hours * 3600), 'comment': args.comment})
            save_manual(week, items)
        elif args.action == 'rm':
            week = args.week if '-W' in args.week.upper() else current_week(week_range(args.week)[0])
            items = load_manual(week)
            if not 0 <= args.index < len(items):
                print(f'timesheet: нет ручной записи #{args.index}', file=sys.stderr)
                return 2
            items.pop(args.index)
            save_manual(week, items)
        else:
            week = args.week if args.week and '-W' in args.week.upper() else \
                current_week(week_range(args.week)[0] if args.week else None)
            items = load_manual(week)
        for i, it in enumerate(items):
            print(f'{i}  {it["sheet"]:<8} {it["day"]}  {it["key"]:<10} {hours(it["seconds"])}  {it.get("comment", "")}')
        return 0

    try:
        week, rules = _load(args)
    except RulesError as e:
        print(f'timesheet: {e}', file=sys.stderr)
        return 2
    if '-W' not in week.upper():
        week = current_week(week_range(week)[0])
    worklogs = fetch_worklogs(rules, week)
    if args.cmd == 'summary':
        print(render(summary(rules, worklogs, week), week))
        return 0
    lines = draft_client(rules, worklogs, load_activity(rules, week), load_manual(week), week)
    path = save_draft(week, lines)
    print(render_draft(lines, week))
    print(f'\nЧерновик записан: {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
