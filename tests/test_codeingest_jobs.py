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


def test_k8s_block_scalar_schedule_is_a_schedule(tmp_path):
    write(
        tmp_path,
        "deploy/cron.yaml",
        "kind: CronJob\nmetadata:\n  name: x\nspec:\n  schedule: |\n    0 2 * * *\n",
    )
    result = run_jobs(tmp_path)
    assert only(result, "deploy/cron.yaml")[1] == "0 2 * * *"
    assert row(result).detail == _coverage.JOBS_DETAIL


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
        "from celery.schedules import crontab\n"
        "from datetime import timedelta\n"
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
    assert row(result).detail == f"{_coverage.JOBS_DETAIL}; proj/celery.py:6"
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


# --- fix round 1 -----------------------------------------------------------------


def blob_of(result) -> str:
    return " ".join(s.l2_md + s.l3_md for s in result.sections)


@needs_ts
def test_spring_time_unit_is_applied_or_dynamic(tmp_path):
    write(
        tmp_path,
        "A.java",
        "class A {\n"
        "  @Scheduled(fixedRate = 5, timeUnit = TimeUnit.SECONDS)\n"
        "  void a() {}\n"
        "  @Scheduled(fixedDelay = 2, timeUnit = TimeUnit.MINUTES)\n"
        "  void b() {}\n"
        "  @Scheduled(fixedRate = 5, timeUnit = unit)\n"
        "  void c() {}\n"
        '  @Scheduled(cron = "-")\n'
        "  void d() {}\n"
        "}\n",
    )
    result = run_jobs(tmp_path)
    got = {r[0]: r[1] for r in rows_of(result, "A.java")}
    assert got == {
        "a": "interval 5s",
        "b": "interval 2m",
        "c": "(dynamic)",
        "d": "disabled",
    }
    assert "A.java:6" in row(result).detail


@needs_ts
def test_spring_qualified_annotation_and_schedules_container(tmp_path):
    write(
        tmp_path,
        "B.java",
        "class B {\n"
        '  @org.springframework.scheduling.annotation.Scheduled(cron = "0 0 1 * * *")\n'
        "  void q() {}\n"
        '  @Schedules({@Scheduled(cron = "0 0 2 * * *"), @Scheduled(fixedRate = 1000)})\n'
        "  void many() {}\n"
        "  @Schedules(OTHER)\n"
        "  void opaque() {}\n"
        "}\n",
    )
    result = run_jobs(tmp_path)
    got = sorted((r[0], r[1]) for r in rows_of(result, "B.java"))
    assert got == [
        ("many", "0 0 2 * * *"),
        ("many", "interval 1000ms"),
        ("q", "0 0 1 * * *"),
    ]
    assert "B.java:6" in row(result).detail


@needs_ts
def test_symfony_parameter_refs_are_dynamic_and_method_option(tmp_path):
    write(
        tmp_path,
        "src/T.php",
        "<?php\n"
        "#[AsCronTask('%env(NIGHTLY_CRON)%')]\n"
        "class N {}\n"
        "#[AsCronTask('0 3 * * *', method: 'run')]\n"
        "class M { public function run() {} }\n"
        "class O {\n"
        "  #[AsPeriodicTask(frequency: '%app.freq%')]\n"
        "  public function t() {}\n"
        "}\n",
    )
    result = run_jobs(tmp_path)
    got = {r[0]: (r[1], r[2]) for r in rows_of(result, "src/T.php")}
    assert got == {
        "N": ("(dynamic)", "N.__invoke"),
        "M": ("0 3 * * *", "M.run"),
        "t": ("(dynamic)", "O.t"),
    }
    assert "NIGHTLY_CRON" not in blob_of(result) and "app.freq" not in blob_of(result)
    assert row(result).detail.endswith("src/T.php:2; src/T.php:7")


@needs_ts
def test_laravel_never_emits_command_arguments(tmp_path):
    write(
        tmp_path,
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n"
        "  $schedule->exec('mysqldump -uroot -pHUNTER2 db')->daily();\n"
        "  $schedule->command('report:send --tenant=acme')->daily();\n"
        "  $schedule->exec('PGPASSWORD=s3cret pg_dump')->daily();\n"
        "}}\n",
    )
    result = run_jobs(tmp_path)
    names = sorted(r[0] for r in rows_of(result, "app/Console/Kernel.php"))
    assert names == ["(exec)", "(exec)", "report:send"]
    for leaked in ("HUNTER2", "acme", "s3cret", "mysqldump"):
        assert leaked not in blob_of(result)


@needs_ts
def test_laravel_modifiers_are_part_of_the_schedule(tmp_path):
    write(
        tmp_path,
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n"
        "  $schedule->command('a')->daily()->at('13:00');\n"
        "  $schedule->command('b')->weekdays()->hourly();\n"
        "  $schedule->command('c')->daily()->at(env('AT'));\n"
        "}}\n",
    )
    result = run_jobs(tmp_path)
    got = {r[0]: r[1] for r in rows_of(result, "app/Console/Kernel.php")}
    assert got == {"a": "daily at 13:00", "b": "hourly weekdays", "c": "(dynamic)"}
    assert "app/Console/Kernel.php:5" in row(result).detail
    assert "AT" not in blob_of(result).replace("DAT", "")


def test_k8s_deep_nesting_is_a_site_not_a_crash(tmp_path):
    write(tmp_path, "k/c.yaml", "kind: CronJob\nx: " + "[" * 3000 + "]" * 3000 + "\n")
    result = run_jobs(tmp_path)
    assert result.sections == []
    assert row(result).detail == f"{_coverage.JOBS_DETAIL}; k/c.yaml:1"


def test_k8s_list_items_are_read_and_opaque_lists_are_sited(tmp_path):
    write(
        tmp_path,
        "k/l.yaml",
        "apiVersion: v1\nkind: List\nitems:\n"
        "- kind: CronJob\n  metadata: {name: a}\n  spec: {schedule: '0 1 * * *'}\n"
        "- kind: ConfigMap\n  metadata: {name: c}\n",
    )
    result = run_jobs(tmp_path)
    assert rows_of(result, "k/l.yaml")[0][:2] == ["a", "0 1 * * *"]


def test_one_failing_file_cannot_abort_extract(tmp_path, monkeypatch):
    write(tmp_path, "k/c.yaml", K8S)
    write(tmp_path, "m.ts", "export const x = 1;\n")

    def boom(*_a, **_k):
        raise ValueError("boom")

    monkeypatch.setattr(jobs._jobs_k8s, "scan", boom)
    monkeypatch.setattr(jobs, "_scan_source", boom)
    result = run_jobs(tmp_path)
    assert result.sections == []
    assert "k/c.yaml:1" in row(result).detail
    assert any("boom" in w for w in result.warnings)


@needs_ts
def test_bullmq_needs_the_library_and_a_schedule_key(tmp_path):
    write(
        tmp_path,
        "ui.ts",
        "const bulletStyle = 1;\nconst anim = { repeat: { count: 3 } };\n",
    )
    write(
        tmp_path,
        "q.ts",
        "import { Queue } from 'bullmq';\n"
        "const anim = { repeat: { count: 3 } };\n"
        "q.add('legacy', {}, { repeat: { cron: '0 5 * * *' } });\n",
    )
    result = run_jobs(tmp_path)
    assert [s.title for s in result.sections] == ["q.ts"]
    assert rows_of(result, "q.ts")[0][:2] == ["legacy", "0 5 * * *"]


@needs_ts
def test_node_cron_only_calls_bound_to_the_import(tmp_path):
    write(
        tmp_path,
        "a.js",
        "// node-cron lives elsewhere\nagenda.schedule('in 20 minutes', 'send email');\n",
    )
    write(
        tmp_path,
        "b.js",
        "import nodeCron, { schedule as every } from 'node-cron';\n"
        "const other = require('agenda');\n"
        "nodeCron.schedule('0 1 * * *', one);\n"
        "every('0 2 * * *', two);\n"
        "other.schedule('x', 'y');\n"
        "const c = require('node-cron');\n"
        "c.schedule('0 3 * * *', three);\n",
    )
    result = run_jobs(tmp_path)
    assert [s.title for s in result.sections] == ["b.js"]
    assert sorted(r[0] for r in rows_of(result, "b.js")) == ["one", "three", "two"]


# --- fix round 2 -----------------------------------------------------------------

# One secret-shaped string argument per scanner: nothing from it may reach any
# emitted cell, title, summary or coverage detail.
SECRET_CASES = {
    "nest": (
        "s.ts",
        "import { Cron, Interval } from '@nestjs/schedule';\n"
        "class S {\n"
        "  @Cron('0 3 * * *', { name: 'x -pSECRET1' })\n  a() {}\n"
        "  @Interval('a=SECRET2', 5000)\n  b() {}\n}\n",
    ),
    "node-cron": (
        "n.js",
        "const cron = require('node-cron');\n"
        "cron.schedule('* * * * *', f, { name: 'job pw=SECRET3' });\n",
    ),
    "bullmq": (
        "q.ts",
        "import { Queue } from 'bullmq';\n"
        "fetchRepeat('https://u:SECRET4@host/x', { repeat: { every: 1000 } });\n"
        "q.add('n pw=SECRET5', {}, { repeat: { every: 1 } });\n",
    ),
    "celery": (
        "c.py",
        "from celery.schedules import crontab, schedule\n"
        "app.conf.beat_schedule = {\n"
        "  'k pw=SECRET6': {'task': 't pw=SECRET7', 'schedule': 30.0},\n"
        "  'a': {'task': 't', 'schedule': crontab(minute=0, app='redis://u:SECRET28@h')},\n"
        "  'b': {'task': 't', 'schedule': schedule(run_every=10, nowfun='SECRET29')},\n"
        "  'c': {'task': 't', 'schedule': other.schedule('SECRET30')},\n}\n"
        "sender.add_periodic_task(10.0, test.s('SECRET8'), name='n SECRET9')\n",
    ),
    "laravel": (
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n"
        "  $schedule->exec('mysqldump -uroot -pSECRET10 db')->daily();\n"
        "  $schedule->command('PGPASSWORD=SECRET11 pg_dump')->daily();\n"
        "  $schedule->command('report:send --tenant=SECRET12')->daily();\n"
        "  $schedule->job('Jobs\\\\Prune --pw=SECRET13')->daily();\n"
        "  $schedule->command('MYSQL_PWD=\"correct horse battery SECRET26\" mysqldump app')->daily();\n"
        "  $schedule->command('PGPASSWORD=\"hunter2 SECRET27 tail\" pg_dump')->daily();\n}}\n",
    ),
    "symfony": (
        "T.php",
        "<?php\n#[AsCronTask('0 3 * * *', method: 'run --pw=SECRET14')]\nclass M {}\n",
    ),
    "spring": (
        "A.java",
        "class A {\n"
        '  @Scheduled(cron = "0 0 * * * *", name = "n pw=SECRET15")\n  void a() {}\n}\n',
    ),
    "hangfire": (
        "S.cs",
        "class S { void M() {\n"
        '  RecurringJob.AddOrUpdate("id pw=SECRET16", () => Svc.Run(), Cron.Daily);\n'
        '  RecurringJob.AddOrUpdate("b", () => new Mailer("smtp://u:SECRET17@h").Send(), Cron.Daily);\n'
        '  RecurringJob.AddOrUpdate("c", () => Factory.For("Password=SECRET18").Run(), Cron.Daily);\n'
        "}}\n",
    ),
    "quartz": (
        "Q.cs",
        "class Q { void M() {\n"
        '  var t = TriggerBuilder.Create().WithIdentity("t pw=SECRET19")'
        '.ForJob("j SECRET20").WithCronSchedule("0 0 12 * * ?").Build();\n}}\n',
    ),
    "go": (
        "main.go",
        'package main\nimport "github.com/robfig/cron/v3"\n'
        'func main() {\n  c.AddFunc("* * * * *", NewJob("SECRET21"))\n'
        '  c.AddJob("* * * * *", &Report{Token: "SECRET22"})\n}\n',
    ),
    "k8s": (
        "k/c.yaml",
        "kind: CronJob\nmetadata:\n  name: 'n SECRET23'\nspec:\n  schedule: '0 1 * * *'\n"
        "  jobTemplate:\n    spec:\n      template:\n        spec:\n          containers:\n"
        "          - name: 'c SECRET24'\n            image: i\n            env:\n"
        "            - {name: P, value: SECRET25}\n",
    ),
}


@needs_ts
@pytest.mark.parametrize("case", sorted(SECRET_CASES))
def test_no_secret_shaped_argument_reaches_any_cell(tmp_path, case):
    rel, text = SECRET_CASES[case]
    write(tmp_path, rel, text)
    result = run_jobs(tmp_path)
    assert result.sections, case
    everything = " ".join(
        [blob_of(result)]
        + [s.title + s.summary for s in result.sections]
        + [r.detail for r in result.coverage]
    )
    assert "SECRET" not in everything, everything


@needs_ts
def test_unsafe_names_become_dynamic_with_a_site_and_safe_ones_survive(tmp_path):
    write(tmp_path, *SECRET_CASES["hangfire"])
    result = run_jobs(tmp_path)
    got = {(r[0], r[2]) for r in rows_of(result, "S.cs")}
    assert got == {("(dynamic)", "Svc.Run"), ("b", "Send"), ("c", "Run")}
    assert "S.cs:2" in row(result).detail


@needs_ts
def test_bullmq_name_only_from_queue_add_calls(tmp_path):
    write(tmp_path, *SECRET_CASES["bullmq"])
    names = sorted(r[0] for r in rows_of(run_jobs(tmp_path), "q.ts"))
    assert names == ["(dynamic)", "(unnamed)"]


@needs_ts
def test_spring_string_keys_apply_time_unit(tmp_path):
    write(
        tmp_path,
        "A.java",
        "class A {\n"
        '  @Scheduled(fixedRateString = "5", timeUnit = TimeUnit.SECONDS)\n  void a() {}\n'
        '  @Scheduled(fixedDelayString = "10", timeUnit = TimeUnit.MINUTES)\n  void b() {}\n'
        '  @Scheduled(fixedRateString = "7")\n  void c() {}\n}\n',
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "A.java")}
    assert got == {"a": "interval 5s", "b": "interval 10m", "c": "interval 7ms"}


@needs_ts
def test_bull_gate_matches_nest_bull_and_unreadable_repeat_is_dynamic(tmp_path):
    write(
        tmp_path,
        "p.ts",
        "import { InjectQueue } from '@nestjs/bull';\n"
        "class P { go() {\n"
        "  this.q.add('rep', {}, { repeat: { cron: '0 1 * * *' } });\n"
        "  this.q.add('spread', {}, { repeat: { ...opts } });\n"
        "  this.q.add('ident', {}, { repeat: opts });\n"
        "  this.q.add('lit', {}, { repeat: true });\n}}\n",
    )
    result = run_jobs(tmp_path)
    got = {r[0]: r[1] for r in rows_of(result, "p.ts")}
    assert got == {"rep": "0 1 * * *", "spread": "(dynamic)", "ident": "(dynamic)"}
    assert row(result).detail.endswith("p.ts:4; p.ts:5")


@needs_ts
def test_node_cron_require_forms(tmp_path):
    write(
        tmp_path,
        "a.ts",
        "import cron = require('node-cron');\ncron.schedule('0 1 * * *', one);\n",
    )
    write(tmp_path, "b.js", "require('node-cron').schedule('0 2 * * *', two);\n")
    result = run_jobs(tmp_path)
    assert rows_of(result, "a.ts")[0][:2] == ["one", "0 1 * * *"]
    assert rows_of(result, "b.js")[0][:2] == ["two", "0 2 * * *"]


@needs_ts
def test_laravel_bare_at_is_daily_at(tmp_path):
    write(
        tmp_path,
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n"
        "  $schedule->command('a')->at('13:00');\n}}\n",
    )
    assert (
        rows_of(run_jobs(tmp_path), "app/Console/Kernel.php")[0][1] == "daily at 13:00"
    )


@needs_ts
def test_symfony_non_literal_method_is_a_site(tmp_path):
    write(
        tmp_path,
        "T.php",
        "<?php\n#[AsCronTask('0 3 * * *', method: self::M)]\nclass M {}\n",
    )
    result = run_jobs(tmp_path)
    assert rows_of(result, "T.php")[0][2] == "-"
    assert "T.php:2" in row(result).detail


def test_k8s_cronjob_list_items_without_kind(tmp_path):
    write(
        tmp_path,
        "k.yaml",
        "kind: CronJobList\nitems:\n- metadata: {name: a}\n  spec: {schedule: '0 1 * * *'}\n",
    )
    assert rows_of(run_jobs(tmp_path), "k.yaml")[0][:2] == ["a", "0 1 * * *"]


def test_each_yaml_manifest_is_read_once(tmp_path, monkeypatch):
    write(tmp_path, "k/c.yaml", K8S)
    reads: list[str] = []
    real = jobs._read

    def counting(root, rel):
        reads.append(rel)
        return real(root, rel)

    monkeypatch.setattr(jobs, "_read", counting)
    run_jobs(tmp_path)
    assert reads.count("k/c.yaml") == 1


# --- fix round 3 -----------------------------------------------------------------


@needs_ts
def test_laravel_command_name_is_first_token_only_when_name_shaped(tmp_path):
    write(
        tmp_path,
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n"
        "  $schedule->command('report:send --tenant=acme')->daily();\n"
        "  $schedule->command('X=1 run')->daily();\n"
        "  $schedule->command('MYSQL_PWD=\"a b\" dump')->daily();\n"
        "}}\n",
    )
    result = run_jobs(tmp_path)
    names = sorted(r[0] for r in rows_of(result, "app/Console/Kernel.php"))
    assert names == ["(dynamic)", "(dynamic)", "report:send"]
    assert "Kernel.php:4" in row(result).detail and "Kernel.php:5" in row(result).detail


@needs_ts
def test_every_dynamic_name_leaves_a_site(tmp_path):
    write(
        tmp_path,
        "S.cs",
        "class S { void M() { RecurringJob.AddOrUpdate(Id(), () => X.Y(), Cron.Daily); } }\n",
    )
    write(
        tmp_path,
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n  $schedule->job($x)->daily();\n}}\n",
    )
    detail = row(run_jobs(tmp_path)).detail
    assert "app/Console/Kernel.php:3" in detail


@needs_ts
@pytest.mark.parametrize(
    "value",
    [
        "opts as RepeatOptions",
        "opts!",
        "c ? x : y",
        "await getOpts()",
        "(opts)",
        "opts satisfies R",
    ],
)
def test_bullmq_non_literal_repeat_forms_are_dynamic(tmp_path, value):
    write(
        tmp_path,
        "q.ts",
        f"import {{ Queue }} from 'bullmq';\nasync function f() {{ q.add('j', {{}}, {{ repeat: {value} }}); }}\n",
    )
    result = run_jobs(tmp_path)
    assert rows_of(result, "q.ts")[0][:2] == ["j", "(dynamic)"]
    assert "q.ts:2" in row(result).detail


@needs_ts
def test_celery_schedule_calls_keep_only_known_fields_from_celery(tmp_path):
    write(
        tmp_path,
        "c.py",
        "from celery.schedules import crontab as cron, schedule, solar\n"
        "app.conf.beat_schedule = {\n"
        "  'ok': {'task': 't', 'schedule': cron('*/15', 4)},\n"
        "  'sun': {'task': 't', 'schedule': solar('sunset', -37.81, 144.96)},\n"
        "  'ev': {'task': 't', 'schedule': schedule(run_every=10)},\n"
        "  'bad1': {'task': 't', 'schedule': cron(minute=0, app='x')},\n"
        "  'bad2': {'task': 't', 'schedule': schedule(run_every=10, nowfun='x')},\n"
        "  'bad3': {'task': 't', 'schedule': other.crontab(minute=0)},\n"
        "  'bad4': {'task': 't', 'schedule': timedelta(seconds=3)},\n"
        "}\n",
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "c.py")}
    assert got == {
        "ok": "cron('*/15', 4)",
        "sun": "solar('sunset', -37.81, 144.96)",
        "ev": "schedule(run_every=10)",
        "bad1": "(dynamic)",
        "bad2": "(dynamic)",
        "bad3": "(dynamic)",
        "bad4": "(dynamic)",
    }


def test_name_only_backslash_is_a_namespace_separator_not_an_escape():
    from strata_kb.codeingest.extractors._jobs_model import name_only

    assert name_only("App\\Jobs\\Prune") == "App\\Jobs\\Prune"
    for bad in ("b\\tX", "a\\nb", "\\x41", "a\\\\b", "a\\u0041b", "a=b", 'a"b'):
        assert name_only(bad) is None, bad


# --- fix round 4 -----------------------------------------------------------------


def test_schedule_only_accepts_cron_and_interval_shapes_and_rejects_the_rest():
    from strata_kb.codeingest.extractors._jobs_model import schedule_only

    for good in ("0 3 * * *", "@every 1h30m", "0 0 12 * * ?", "0 0 ? * MON#2", "5m"):
        assert schedule_only(good) == good, good
    for bad in (
        None,
        "",
        "x" * 65,
        "redis://u:p@h",
        "pw=X",
        "a'b",
        'a"b',
        "a\nb",
        "a;b",
        "${x}",
        "%env(X)%",
        "a(b)",
    ):
        assert schedule_only(bad) is None, bad


# the schedule position of every scanner, fed a secret-shaped value
SCHEDULE_SECRET_CASES = {
    "nest": (
        "s.ts",
        "import { Cron } from '@nestjs/schedule';\nclass S {\n"
        "  @Cron('pw=SECRETN1')\n  a() {}\n"
        "  @Cron('redis://u:SECRETN2@h')\n  b() {}\n}\n",
    ),
    "node-cron": (
        "n.js",
        "const cron = require('node-cron');\n"
        "cron.schedule('redis://u:SECRETC1@h', f);\n"
        "cron.schedule('pw=SECRETC2', g);\n",
    ),
    "bullmq": (
        "q.ts",
        "import { Queue } from 'bullmq';\n"
        "q.add('a', {}, { repeat: { pattern: 'pw=SECRETB1' } });\n"
        "q.add('b', {}, { repeat: { cron: 'redis://u:SECRETB2@h' } });\n",
    ),
    "celery": (
        "c.py",
        "from celery.schedules import crontab\n"
        "app.conf.beat_schedule = {\n"
        " 'a': {'task': 't', 'schedule': crontab(hour='redis://u:SECRETY1@h')},\n"
        " 'b': {'task': 't', 'schedule': crontab(minute=b'SECRETY2')},\n"
        " 'c': {'task': 't', 'schedule': crontab(minute='pw=SECRETY3')},\n"
        " 'd': {'task': 't', 'schedule': crontab(minute=f'SECRETY4')},\n}\n",
    ),
    "laravel": (
        "app/Console/Kernel.php",
        "<?php\nclass K { function schedule($schedule) {\n"
        "  $schedule->command('a')->cron('pw=SECRETL1');\n"
        "  $schedule->command('b')->dailyAt('x=SECRETL2');\n"
        "  $schedule->command('c')->hourly()->between('a=SECRETL3', '17:00');\n"
        "  $schedule->command('d')->daily()->days('SECRETL4=');\n}}\n",
    ),
    "symfony": (
        "T.php",
        "<?php\n#[AsCronTask('pw=SECRETS1')]\nclass M {}\n"
        "#[AsPeriodicTask('pw=SECRETS2')]\nclass N {}\n",
    ),
    "spring": (
        "A.java",
        "class A {\n"
        '  @Scheduled(cron = "pw=SECRETJ1")\n  void a() {}\n'
        '  @Scheduled(every = "pw=SECRETJ2")\n  void b() {}\n'
        '  @Scheduled(fixedRateString = "pw=SECRETJ3")\n  void c() {}\n}\n',
    ),
    "hangfire": (
        "S.cs",
        "class S { void M() {\n"
        '  RecurringJob.AddOrUpdate("a", () => X.Y(), "pw=SECRETH1");\n'
        '  RecurringJob.AddOrUpdate("b", () => X.Y(), Cron.Daily("pw=SECRETH2"));\n'
        '  RecurringJob.AddOrUpdate("c", () => X.Y(), "redis://u:SECRETH3@h");\n}}\n',
    ),
    "quartz": (
        "Q.cs",
        "class Q { void M() {\n"
        '  var t = TriggerBuilder.Create().WithCronSchedule("pw=SECRETQ1").Build();\n}}\n',
    ),
    "go": (
        "main.go",
        'package main\nimport "github.com/robfig/cron/v3"\n'
        'func main() { c.AddFunc("pw=SECRETG1", job) }\n',
    ),
    "rust": (
        "m.rs",
        'use tokio_cron_scheduler::Job;\nfn main() { Job::new("pw=SECRETR1", run); }\n',
    ),
    "k8s": (
        "k/c.yaml",
        "kind: CronJob\nmetadata:\n  name: n\nspec:\n  schedule: 'pw=SECRETK1'\n",
    ),
}


@needs_ts
@pytest.mark.parametrize("case", sorted(SCHEDULE_SECRET_CASES))
def test_secret_shaped_schedule_is_dynamic_in_every_scanner(tmp_path, case):
    rel, text = SCHEDULE_SECRET_CASES[case]
    write(tmp_path, rel, text)
    result = run_jobs(tmp_path)
    assert result.sections, case
    rows = rows_of(result, rel)
    assert rows and {r[1] for r in rows} == {"(dynamic)"}, rows
    everything = " ".join(
        [blob_of(result)]
        + [s.title + s.summary for s in result.sections]
        + [r.detail for r in result.coverage]
    )
    assert "SECRET" not in everything, everything


@needs_ts
def test_celery_schedule_is_rebuilt_from_known_fields_never_raw_text(tmp_path):
    write(
        tmp_path,
        "c.py",
        "from celery.schedules import crontab\n"
        "app.conf.beat_schedule = {\n"
        " 'k': {'task': 't', 'schedule': crontab(minute=0,  # pw=LEAKA1\n  hour=3)},\n"
        " 'k2': {'task': 't', 'schedule': crontab(\n  minute=0  # token LEAKA2\n )},\n"
        " 'k3': {'task': 't', 'schedule': crontab(minute=0, hour=3,)},\n}\n",
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "c.py")}
    assert got == {
        "k": "crontab(minute=0, hour=3)",
        "k2": "crontab(minute=0)",
        "k3": "crontab(minute=0, hour=3)",
    }


@needs_ts
def test_hangfire_cron_call_is_rebuilt_without_comments(tmp_path):
    write(
        tmp_path,
        "S.cs",
        "class S { void M() {\n"
        '  RecurringJob.AddOrUpdate("a", () => X.Y(), Cron.Daily(/* pw=LEAKH */ 1, 30));\n'
        '  RecurringJob.AddOrUpdate("b", () => X.Y(), Cron . /* pw=LEAKI */ Daily);\n'
        '  RecurringJob.AddOrUpdate("c", () => X.Y(), Cron.Daily("LEAKJ"));\n}}\n',
    )
    got = {r[0]: r[1] for r in rows_of(run_jobs(tmp_path), "S.cs")}
    assert got == {"a": "Cron.Daily(1, 30)", "b": "Cron.Daily", "c": "(dynamic)"}


@needs_ts
def test_bullmq_shorthand_repeat_is_dynamic_with_a_site(tmp_path):
    write(
        tmp_path,
        "q.ts",
        "import { Queue } from 'bullmq';\nconst repeat = mk('LEAKF1');\n"
        "q.add('a', {}, { repeat });\n",
    )
    result = run_jobs(tmp_path)
    assert rows_of(result, "q.ts")[0][:2] == ["a", "(dynamic)"]
    assert "q.ts:3" in row(result).detail


@needs_ts
@pytest.mark.parametrize(
    "imports,call",
    [
        ("import datetime as dt\n", "dt.timedelta(minutes=5)"),
        ("import datetime\n", "datetime.timedelta(minutes=5)"),
        ("import celery\n", "celery.schedules.crontab(minute=0)"),
        ("import celery.schedules\n", "celery.schedules.crontab(minute=0)"),
        ("from celery import schedules as s\n", "s.crontab(minute=0)"),
        ("from celery.schedules import *\n", "crontab(minute=0)"),
        ("from celery.schedules import *\n", "solar('sunset', 1, 2)"),
        ("from celery.schedules import *\n", "schedule(run_every=10)"),
    ],
)
def test_celery_module_bindings(tmp_path, imports, call):
    write(
        tmp_path,
        "c.py",
        imports
        + f"app.conf.beat_schedule = {{'k': {{'task': 't', 'schedule': {call}}}}}\n",
    )
    (found,) = rows_of(run_jobs(tmp_path), "c.py")
    assert found[1] == call


@needs_ts
def test_celery_unbound_module_alias_stays_dynamic(tmp_path):
    write(
        tmp_path,
        "c.py",
        "import other as dt\napp.conf.beat_schedule = "
        "{'k': {'task': 't', 'schedule': dt.timedelta(minutes=5)}}\n",
    )
    assert rows_of(run_jobs(tmp_path), "c.py")[0][1] == "(dynamic)"


def test_name_only_accepts_php_namespace_segments_that_look_like_hex_escapes():
    from strata_kb.codeingest.extractors._jobs_model import name_only

    for good in ("App\\UData", "App\\XCase", "App\\Jobs\\Xf", "A\\U0041"):
        assert name_only(good) == good, good
    for bad in ("b\\tX", "a\\nb", "\\x41", "a\\\\b", "a\\u0041b", "a\\x41"):
        assert name_only(bad) is None, bad
