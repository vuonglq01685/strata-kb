"""Go exported symbols (robfig/cron jobs: test_codeingest_jobs.py)."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.lintcore import table_rows
from tests.go_support import everything, gomod, run_symbols, write

# --- symbols -----------------------------------------------------------------


def sym_rows(result) -> list[tuple[str, str, str]]:
    return sorted(
        (r[0], r[1], r[2]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )


def go_row(result, scope: str = "."):
    (found,) = [r for r in result.coverage if r.scope == scope and r.framework == "go"]
    return found


def test_go_symbols_capitalised_top_level_names_only(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "pkg/api.go",
        """package pkg

import "fmt"

const Version = "1.0"
const hidden = 1
const (
	First = iota
	Second
	third
)
var Default = New()
var lower = 2
var (
	A, b = 1, 2
	_    = 3
)
type Server struct{ Name string }
type Handler interface{ Serve() }
type ID int
type Alias = string
type hiddenType struct{}
type (
	Pair  struct{}
	local int
)
type Generic[T any] struct{}

func New() *Server { return nil }
func helper()      {}
func Éclair()      {}
func élan()        {}
func Map[K comparable, V any](m map[K]V) {}

func (s *Server) Start() {}
func (s Server) stop()   {}

func init() { fmt.Println() }
func main() {}
""",
    )
    result = run_symbols(tmp_path)
    assert sym_rows(result) == [
        ("A", "const", "pkg/api.go"),
        ("Alias", "type", "pkg/api.go"),
        ("Default", "const", "pkg/api.go"),
        ("First", "const", "pkg/api.go"),
        ("Generic", "class", "pkg/api.go"),
        ("Handler", "interface", "pkg/api.go"),
        ("ID", "type", "pkg/api.go"),
        ("Map", "function", "pkg/api.go"),
        ("New", "function", "pkg/api.go"),
        ("Pair", "class", "pkg/api.go"),
        ("Second", "const", "pkg/api.go"),
        ("Server", "class", "pkg/api.go"),
        ("Version", "const", "pkg/api.go"),
        ("Éclair", "function", "pkg/api.go"),
    ]
    assert go_row(result).status == "complete"


def test_go_symbols_skip_test_files_and_never_emit_values(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "cfg/cfg.go",
        """package cfg

const APIKey = "sk_live_CONSTSECRET123"
var Token = "ghp_VARTOKEN" + APIKey
const (
	DBPassword string = "hunter2-SECRETPW"
)
""",
    )
    write(
        tmp_path,
        "cfg/cfg_test.go",
        "package cfg\n\nconst TestOnly = 1\n\nfunc TestSomething() {}\n",
    )
    result = run_symbols(tmp_path)
    assert sym_rows(result) == [
        ("APIKey", "const", "cfg/cfg.go"),
        ("DBPassword", "const", "cfg/cfg.go"),
        ("Token", "const", "cfg/cfg.go"),
    ]
    blob = everything(result)
    for secret in ("CONSTSECRET123", "VARTOKEN", "SECRETPW", "TestOnly"):
        assert secret not in blob


def test_go_symbols_syntax_error_is_a_site(tmp_path):
    gomod(tmp_path)
    write(tmp_path, "bad/bad.go", "package bad\n\nfunc Broken( {\n")
    result = run_symbols(tmp_path)
    assert go_row(result).status == "partial"
    assert go_row(result).detail.startswith("bad/bad.go:")
