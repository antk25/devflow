import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RULES_PATH = Path.home() / '.config' / 'devflow' / 'timesheet.json'
INTEGRATIONS = Path(__file__).resolve().parents[2] / 'integrations'
MSK = timezone(timedelta(hours=3))
MODES = ('per-issue', 'bucket')
WEEKDAYS = ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс')


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='timesheet')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('summary')
    p.add_argument('--week', default=None)
    p.add_argument('--rules', type=Path, default=RULES_PATH)
    args = ap.parse_args(argv)
    week = args.week or current_week()
    try:
        rules = load_rules(args.rules, accounts_available())
    except RulesError as e:
        print(f'timesheet: {e}', file=sys.stderr)
        return 2
    print(render(summary(rules, fetch_worklogs(rules, week), week), week))
    return 0


if __name__ == '__main__':
    sys.exit(main())
