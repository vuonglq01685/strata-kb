"""jobs extractor: framework schedulers in every supported language plus k8s
CronJob, and the always-partial `jobs` coverage row per scope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata_kb.codeingest.extractors import _coverage, _ts, jobs
from strata_kb.codeingest.extractors._slugs import assign_slugs
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows

needs_ts = pytest.mark.skipif(not _ts.available(), reason="code extra not installed")


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def package(root: Path, app: str, *deps: str) -> None:
    manifest = {"name": "app", "dependencies": dict.fromkeys(deps, "*")}
    write(
        root,
        f"{app}/package.json" if app != "." else "package.json",
        json.dumps(manifest),
    )


def run_jobs(root: Path):
    opts = CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="r"
    )
    return jobs.JobsExtractor().extract(root, opts)


def rows_of(result, file: str) -> list[list[str]]:
    (sec,) = [s for s in result.sections if s.title == file]
    return table_rows(sec.l2_md)[1:]


def row(result, scope: str = "."):
    (found,) = [r for r in result.coverage if r.scope == scope]
    return found


def only(result, file: str) -> list[str]:
    (found,) = rows_of(result, file)
    return found


# --- structure -------------------------------------------------------------


def test_extractor_name_and_registered():
    from strata_kb.codeingest.extractors import ALL_EXTRACTORS

    assert jobs.JobsExtractor().name == "jobs"
    assert any(e.name == "jobs" for e in ALL_EXTRACTORS)


@needs_ts
def test_nest_cron_job_listed_and_scope_partial(tmp_path):
    package(tmp_path, "apps/api", "@nestjs/core", "@nestjs/schedule")
    write(
        tmp_path,
        "apps/api/src/maintenance/maintenance.service.ts",
        "import { Cron } from '@nestjs/schedule';\n"
        "export class MaintenanceService {\n"
        "  @Cron('0 3 * * *')\n"
        "  async cleanup() {}\n"
        "}\n",
    )
    result = run_jobs(tmp_path)
    (sec,) = result.sections
    stem = "apps/api/src/maintenance/maintenance.service"
    assert sec.id == f"job.{assign_slugs([stem])[0]}"
    assert sec.group == "jobs"
    assert table_rows(sec.l2_md)[0] == ["Name", "Schedule", "Handler", "File"]
    assert only(result, "apps/api/src/maintenance/maintenance.service.ts") == [
        "cleanup",
        "0 3 * * *",
        "MaintenanceService.cleanup",
        "apps/api/src/maintenance/maintenance.service.ts",
    ]
    found = row(result, "apps/api")
    assert (found.area, found.framework, found.status) == ("jobs", "-", "partial")
    assert found.detail == _coverage.JOBS_DETAIL


@needs_ts
def test_nest_interval_timeout_and_name_option(tmp_path):
    write(
        tmp_path,
        "svc.ts",
        "import { Cron, Interval, Timeout } from '@nestjs/schedule';\n"
        "class S {\n"
        "  @Cron('*/5 * * * *', { name: 'nightly' })\n"
        "  a() {}\n"
        "  @Interval('poll', 60000)\n"
        "  b() {}\n"
        "  @Interval(1500)\n"
        "  c() {}\n"
        "  @Timeout(10000)\n"
        "  d() {}\n"
        "}\n",
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "svc.ts")}
    assert got == {
        "nightly": "*/5 * * * *",
        "poll": "interval 60000ms",
        "c": "interval 1500ms",
        "d": "timeout 10000ms",
    }


@needs_ts
def test_non_literal_schedule_is_dynamic_with_site_and_no_value_leak(tmp_path):
    write(
        tmp_path,
        "svc.ts",
        "import { Cron, CronExpression } from '@nestjs/schedule';\n"
        "class S {\n"
        "  @Cron(CronExpression.EVERY_HOUR)\n"
        "  a() {}\n"
        "  @Cron(process.env.SECRET_CRON)\n"
        "  b() {}\n"
        "}\n",
    )
    result = run_jobs(tmp_path)
    got = {r[0]: r[1] for r in rows_of(result, "svc.ts")}
    assert got == {"a": "(dynamic)", "b": "(dynamic)"}
    assert row(result).detail == f"{_coverage.JOBS_DETAIL}; svc.ts:3; svc.ts:5"
    blob = " ".join(s.l2_md + s.l3_md for s in result.sections)
    assert "SECRET_CRON" not in blob and "EVERY_HOUR" not in blob


@needs_ts
def test_nest_decorators_ignored_without_schedule_import(tmp_path):
    write(tmp_path, "x.ts", "class S { @Cron('* * * * *') a() {} }\n")
    result = run_jobs(tmp_path)
    assert result.sections == []
    assert row(result).detail == _coverage.JOBS_DETAIL


# --- k8s -------------------------------------------------------------------

K8S = """\
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-report
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: report
              image: registry.example/report:1
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: cfg
"""


def test_k8s_cronjob_listed(tmp_path):
    write(tmp_path, "deploy/cron.yaml", K8S)
    result = run_jobs(tmp_path)
    assert result.sections[0].id == "job.deploy-cron"
    assert only(result, "deploy/cron.yaml") == [
        "nightly-report",
        "0 2 * * *",
        "report",
        "deploy/cron.yaml",
    ]
    found = row(result)
    assert found.status == "partial" and found.detail == _coverage.JOBS_DETAIL


def test_k8s_works_without_code_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(_ts, "available", lambda: False)
    write(tmp_path, "deploy/cron.yml", K8S)
    result = run_jobs(tmp_path)
    assert len(result.sections) == 1
    assert row(result).detail == _coverage.JOBS_DETAIL
    assert result.warnings == []


def test_k8s_templated_schedule_is_dynamic_with_site(tmp_path):
    write(
        tmp_path,
        "chart/cron.yaml",
        'kind: CronJob\nmetadata:\n  name: x\nspec:\n  schedule: "{{ .Values.cron }}"\n',
    )
    result = run_jobs(tmp_path)
    assert only(result, "chart/cron.yaml")[1] == "(dynamic)"
    assert row(result).detail == f"{_coverage.JOBS_DETAIL}; chart/cron.yaml:5"


def test_k8s_unparseable_yaml_is_a_site_not_a_crash(tmp_path):
    write(tmp_path, "chart/cron.yaml", "kind: CronJob\n{{- if .Values.on }}\n")
    result = run_jobs(tmp_path)
    assert result.sections == []
    assert row(result).detail == f"{_coverage.JOBS_DETAIL}; chart/cron.yaml:1"


def test_github_actions_schedule_excluded(tmp_path):
    write(
        tmp_path,
        ".github/workflows/nightly.yml",
        "on:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  b:\n    runs-on: x\n",
    )
    result = run_jobs(tmp_path)
    assert result.sections == [] and result.coverage == []


# --- JVM / .NET ---------------------------------------------------------------


@needs_ts
def test_spring_scheduled_cron_and_fixed_rate(tmp_path):
    write(
        tmp_path,
        "src/main/java/app/Jobs.java",
        "package app;\n"
        "public class Jobs {\n"
        '  @Scheduled(cron = "0 0 * * * *")\n'
        "  public void hourly() {}\n"
        "  @Scheduled(fixedRate = 5000)\n"
        "  public void often() {}\n"
        '  @Scheduled(fixedDelayString = "${app.delay}")\n'
        "  public void configured() {}\n"
        "  @Scheduled\n"
        "  public void bare() {}\n"
        "}\n",
    )
    result = run_jobs(tmp_path)
    got = {r[0]: (r[1], r[2]) for r in rows_of(result, "src/main/java/app/Jobs.java")}
    assert got == {
        "hourly": ("0 0 * * * *", "Jobs.hourly"),
        "often": ("interval 5000ms", "Jobs.often"),
        "configured": ("(dynamic)", "Jobs.configured"),
        "bare": ("(dynamic)", "Jobs.bare"),
    }
    assert "app.delay" not in result.sections[0].l2_md


@needs_ts
def test_quarkus_every_and_micronaut_fixed_delay(tmp_path):
    write(
        tmp_path,
        "src/main/java/Q.java",
        "class Q {\n"
        '  @Scheduled(every = "10s", identity = "tick")\n'
        "  void a() {}\n"
        '  @Scheduled(fixedDelay = "5m")\n'
        "  void b() {}\n"
        '  @Scheduled(cron = "{my.cron}")\n'
        "  void c() {}\n"
        "}\n",
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "src/main/java/Q.java")}
    assert got == {"tick": "every 10s", "b": "every 5m", "c": "(dynamic)"}


@needs_ts
def test_kotlin_scheduled(tmp_path):
    write(
        tmp_path,
        "src/main/kotlin/K.kt",
        'class K {\n  @Scheduled(cron = "0 30 4 * * *")\n  fun nightly() {}\n}\n',
    )
    assert only(run_jobs(tmp_path), "src/main/kotlin/K.kt")[:3] == [
        "nightly",
        "0 30 4 * * *",
        "K.nightly",
    ]


@needs_ts
def test_hangfire_recurring_job(tmp_path):
    write(
        tmp_path,
        "Startup.cs",
        "class Startup {\n"
        "  void M() {\n"
        '    RecurringJob.AddOrUpdate("sync", () => Svc.Run(), Cron.Daily());\n'
        '    RecurringJob.AddOrUpdate<IFoo>(x => x.Do(), "0 3 * * *");\n'
        '    RecurringJob.AddOrUpdate("dyn", () => Svc.Go(), expr);\n'
        "  }\n"
        "}\n",
    )
    got = {r[0]: (r[1], r[2]) for r in rows_of(run_jobs(tmp_path), "Startup.cs")}
    assert got == {
        "sync": ("Cron.Daily()", "Svc.Run"),
        "Do": ("0 3 * * *", "IFoo.Do"),
        "dyn": ("(dynamic)", "Svc.Go"),
    }


@needs_ts
def test_quartz_with_cron_schedule(tmp_path):
    write(
        tmp_path,
        "Q.cs",
        "class Q {\n  void M() {\n"
        '    var t = TriggerBuilder.Create().WithIdentity("t1").ForJob("j1")'
        '.WithCronSchedule("0 0 12 * * ?").Build();\n  }\n}\n',
    )
    assert only(run_jobs(tmp_path), "Q.cs")[:3] == ["t1", "0 0 12 * * ?", "j1"]


@needs_ts
def test_background_service_is_hosted(tmp_path):
    write(
        tmp_path,
        "Worker.cs",
        "class Worker : BackgroundService {}\n"
        "class Plain : IDisposable {}\n"
        "abstract class Base : BackgroundService {}\n",
    )
    assert rows_of(run_jobs(tmp_path), "Worker.cs") == [
        ["Worker", "hosted", "ExecuteAsync", "Worker.cs"]
    ]


# --- Python / PHP ------------------------------------------------------------


@needs_ts
def test_celery_beat_schedule_periodic_task_and_add_periodic_task(tmp_path):
    write(
        tmp_path,
        "proj/celery.py",
        "app.conf.beat_schedule = {\n"
        '    "nightly": {"task": "proj.tasks.clean", "schedule": crontab(minute=0, hour=3)},\n'
        '    "poll": {"task": "proj.tasks.poll", "schedule": 30.0},\n'
        '    "dyn": {"task": "proj.tasks.dyn", "schedule": make_schedule()},\n'
        "}\n"
        "@periodic_task(run_every=timedelta(seconds=30))\n"
        "def beat(): pass\n"
        "@app.on_after_configure.connect\n"
        "def setup(sender, **kw):\n"
        '    sender.add_periodic_task(10.0, test.s("hi"), name="every-ten")\n',
    )
    result = run_jobs(tmp_path)
    got = {r[0]: (r[1], r[2]) for r in rows_of(result, "proj/celery.py")}
    assert got == {
        "nightly": ("crontab(minute=0, hour=3)", "proj.tasks.clean"),
        "poll": ("interval 30.0s", "proj.tasks.poll"),
        "dyn": ("(dynamic)", "proj.tasks.dyn"),
        "beat": ("timedelta(seconds=30)", "beat"),
        "every-ten": ("interval 10.0s", "test"),
    }
    assert row(result).detail == f"{_coverage.JOBS_DETAIL}; proj/celery.py:4"
    assert "hi" not in result.sections[0].l2_md


@needs_ts
def test_laravel_schedule_chains(tmp_path):
    write(
        tmp_path,
        "app/Console/Kernel.php",
        "<?php\nclass Kernel {\n  protected function schedule($schedule) {\n"
        "    $schedule->command('emails:send')->dailyAt('13:00')->withoutOverlapping();\n"
        "    $schedule->job(new Prune)->cron('0 3 * * *');\n"
        "    $schedule->call(function () {})->hourly();\n"
        "    $schedule->command('x:y')->withoutOverlapping();\n"
        "  }\n}\n",
    )
    write(
        tmp_path,
        "routes/console.php",
        "<?php\nSchedule::command('inspire')->everyMinute();\n",
    )
    result = run_jobs(tmp_path)
    kernel = {r[0]: r[1] for r in rows_of(result, "app/Console/Kernel.php")}
    assert kernel == {
        "emails:send": "dailyAt 13:00",
        "Prune": "0 3 * * *",
        "(anonymous)": "hourly",
        "x:y": "(dynamic)",
    }
    assert rows_of(result, "routes/console.php")[0][:2] == ["inspire", "everyMinute"]
    assert "app/Console/Kernel.php:7" in row(result).detail


@needs_ts
def test_symfony_cron_and_periodic_tasks(tmp_path):
    write(
        tmp_path,
        "src/Task.php",
        "<?php\n"
        "#[AsCronTask('0 3 * * *')]\n"
        "class Nightly {}\n"
        "class Other {\n"
        "  #[AsPeriodicTask(frequency: '1 hour')]\n"
        "  public function tick() {}\n"
        "  #[AsPeriodicTask(300)]\n"
        "  public function fast() {}\n"
        "}\n",
    )
    got = {r[0]: (r[1], r[2]) for r in rows_of(run_jobs(tmp_path), "src/Task.php")}
    assert got == {
        "Nightly": ("0 3 * * *", "Nightly.__invoke"),
        "tick": ("every 1 hour", "Other.tick"),
        "fast": ("interval 300s", "Other.fast"),
    }


# --- JS libs / Go / Rust --------------------------------------------------------


@needs_ts
def test_node_cron_and_bullmq(tmp_path):
    write(
        tmp_path,
        "jobs.js",
        "const cron = require('node-cron');\n"
        "const { Queue } = require('bullmq');\n"
        "cron.schedule('*/2 * * * *', sendDigest);\n"
        "cron.schedule('0 0 * * *', () => {});\n"
        "q.add('report', {}, { repeat: { pattern: '0 1 * * *' } });\n"
        "q.add('poll', {}, { repeat: { every: 30000 } });\n",
    )
    got = sorted((r[0], r[1]) for r in rows_of(run_jobs(tmp_path), "jobs.js"))
    assert got == [
        ("(anonymous)", "0 0 * * *"),
        ("poll", "interval 30000ms"),
        ("report", "0 1 * * *"),
        ("sendDigest", "*/2 * * * *"),
    ]


@needs_ts
def test_go_robfig_cron(tmp_path):
    write(
        tmp_path,
        "cmd/main.go",
        'package main\nimport "github.com/robfig/cron/v3"\n'
        "func main() {\n  c := cron.New()\n"
        '  c.AddFunc("@every 5m", cleanup)\n'
        '  c.AddJob("0 * * * *", &Report{})\n'
        "  c.AddFunc(spec, svc.Run)\n}\n",
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "cmd/main.go")}
    assert got == {"cleanup": "@every 5m", "Report": "0 * * * *", "Run": "(dynamic)"}


@needs_ts
def test_rust_tokio_cron_scheduler(tmp_path):
    write(
        tmp_path,
        "src/main.rs",
        "use tokio_cron_scheduler::Job;\n"
        "fn f() {\n"
        '  Job::new("1/10 * * * * *", |_l, _s| {});\n'
        "  Job::new_repeated(Duration::from_secs(8), run_it);\n"
        "}\n",
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "src/main.rs")}
    assert got == {"(anonymous)": "1/10 * * * * *", "run_it": "interval 8s"}


# --- coverage / degrade ------------------------------------------------------------


def test_without_extra_row_is_partial_with_not_installed_and_no_sections(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(_ts, "available", lambda: False)
    package(tmp_path, "apps/api", "@nestjs/schedule")
    write(
        tmp_path,
        "apps/api/s.ts",
        "import { Cron } from '@nestjs/schedule';\nclass S { @Cron('* * * * *') a() {} }\n",
    )
    result = run_jobs(tmp_path)
    assert result.sections == []
    found = row(result, "apps/api")
    assert found.status == "partial"
    assert found.detail == f"{_coverage.JOBS_DETAIL}; {_coverage.NOT_INSTALLED}"
    assert len(result.warnings) == 1 and "strata-kb[code]" in result.warnings[0]


@needs_ts
def test_syntax_error_in_scheduler_file_is_a_site(tmp_path):
    write(
        tmp_path,
        "bad.ts",
        "import { Cron } from '@nestjs/schedule';\nclass S { @Cron('* * * * *') a( {\n",
    )
    assert "bad.ts:" in row(run_jobs(tmp_path)).detail


@needs_ts
def test_scope_without_sources_has_no_row_and_test_files_skipped(tmp_path):
    package(tmp_path, "apps/empty", "react")
    write(tmp_path, "apps/empty/README.md", "x")
    package(tmp_path, "apps/api", "@nestjs/schedule")
    write(tmp_path, "apps/api/main.ts", "export const x = 1;\n")
    write(
        tmp_path,
        "apps/api/s.spec.ts",
        "import { Cron } from '@nestjs/schedule';\nclass S { @Cron('* * * * *') a() {} }\n",
    )
    result = run_jobs(tmp_path)
    assert [r.scope for r in result.coverage] == ["apps/api"]
    assert result.sections == []


@needs_ts
def test_same_stem_files_get_distinct_ids_and_output_is_deterministic(tmp_path):
    for ext in ("ts", "js"):
        write(
            tmp_path,
            f"a/jobs.{ext}",
            "const cron = require('node-cron');\ncron.schedule('* * * * *', go);\n",
        )
    first = run_jobs(tmp_path)
    second = run_jobs(tmp_path)
    assert first == second
    ids = [s.id for s in first.sections]
    assert len(set(ids)) == 2 == len(ids)
