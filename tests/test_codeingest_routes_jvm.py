"""JVM (Java + Kotlin): Spring Boot, Quarkus and Micronaut route adapters,
the request-type field reader, and the java/kotlin exported symbols."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import routes, symbols
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows

SPRING = "org.springframework.boot:spring-boot-starter-web"
QUARKUS = "io.quarkus:quarkus-rest"
MICRONAUT = "io.micronaut:micronaut-http-server-netty"
JAVA = "src/main/java/app"
KOTLIN = "src/main/kotlin/app"


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def gradle(root: Path, artifact: str, app: str = ".") -> None:
    manifest = f"{app}/build.gradle" if app != "." else "build.gradle"
    write(root, manifest, f"dependencies {{\n  implementation '{artifact}'\n}}\n")


def opts(root: Path) -> CodeIngestOptions:
    return CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="r"
    )


def run_routes(root: Path):
    return routes.RoutesExtractor().extract(root, opts(root))


def run_symbols(root: Path):
    return symbols.SymbolsExtractor().extract(root, opts(root))


def section(result, file: str):
    (found,) = [s for s in result.sections if s.title == file]
    return found


def rows_of(result, file: str) -> list[list[str]]:
    return table_rows(section(result, file).l2_md)[1:]


def row(result, scope: str = "."):
    (found,) = [r for r in result.coverage if r.scope == scope]
    return found


def paths(result) -> list[tuple[str, str]]:
    return sorted(
        (r[0], r[1]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )


# --- Spring Boot ------------------------------------------------------------


def test_spring_controller_prefix_path_param_and_request_fields(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/UserController.java",
        """package app;
@RestController
@RequestMapping("/api/users")
public class UserController {
  @GetMapping("/{id}")
  public User get(@PathVariable Long id) { return null; }

  @PostMapping
  public User create(@Valid @RequestBody CreateUserRequest req) { return null; }
}
""",
    )
    write(
        tmp_path,
        f"{JAVA}/CreateUserRequest.java",
        "package app;\npublic record CreateUserRequest(@NotBlank String name, String note) {}\n",
    )
    result = run_routes(tmp_path)
    file = f"{JAVA}/UserController.java"
    assert rows_of(result, file) == [
        ["POST", "/api/users", "UserController.create", file, "CreateUserRequest"],
        ["GET", "/api/users/{id}", "UserController.get", file, ""],
    ]
    l3 = section(result, file).l3_md
    assert "| name | String | yes |" in l3
    assert "| note | String | yes |" in l3  # record component -> required
    assert (row(result).status, row(result).detail) == ("complete", "")


def test_spring_request_mapping_arrays_and_methods(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/ItemController.java",
        """package app;
@Controller
@RequestMapping(path = {"/items", "/v2/items"})
public class ItemController {
  @RequestMapping(value = "/all", method = {RequestMethod.GET, RequestMethod.HEAD})
  String all() { return ""; }
  @RequestMapping(path = {"/a", "/b"}, method = RequestMethod.PUT)
  String put() { return ""; }
  @RequestMapping("/any")
  String any() { return ""; }
  @DeleteMapping(value = "/{id}", produces = "application/json")
  void del() {}
  @PatchMapping(path = "/{id}")
  void patch() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == sorted(
        [("GET", "/items/all"), ("HEAD", "/items/all"), ("GET", "/v2/items/all")]
        + [("HEAD", "/v2/items/all")]
        + [
            (m, f"{p}/{leaf}")
            for p in ("/items", "/v2/items")
            for m, leaf in (("PUT", "a"), ("PUT", "b"))
        ]
        + [("ANY", "/items/any"), ("ANY", "/v2/items/any")]
        + [
            (m, f"{p}/{{id}}")
            for p in ("/items", "/v2/items")
            for m in ("DELETE", "PATCH")
        ]
    )
    assert row(result).status == "complete"


def test_spring_typical_app_reaches_complete(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/OrderController.java",
        """package app;
import io.swagger.v3.oas.annotations.*;
@Tag(name = "orders")
@Validated
@CrossOrigin(origins = "*")
@RestController
@RequestMapping("/orders")
public class OrderController {
  private final OrderService service;
  public OrderController(OrderService service) { this.service = service; }

  @Operation(summary = "list")
  @PreAuthorize("hasRole('ADMIN')")
  @GetMapping
  public List<Order> list(@RequestParam(defaultValue = "0") int page) { return null; }

  @ApiResponse(responseCode = "200")
  @GetMapping("/{id:[0-9]+}")
  public Order get(@PathVariable("id") long id) { return null; }

  @ResponseStatus(HttpStatus.CREATED)
  @PostMapping(consumes = "application/json")
  public Order create(@Valid @RequestBody OrderDto dto) { return null; }

  @ExceptionHandler(NotFound.class)
  public ResponseEntity<String> notFound() { return null; }
}
""",
    )
    write(
        tmp_path,
        f"{JAVA}/OrderDto.java",
        "package app;\npublic class OrderDto {\n  @NotNull private String sku;\n  private int qty;\n  private static final long serialVersionUID = 1L;\n}\n",
    )
    write(
        tmp_path,
        f"{JAVA}/Auth.java",
        'package app;\n@Retention(RetentionPolicy.RUNTIME)\n@PreAuthorize("isAuthenticated()")\npublic @interface Auth {}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete"
    assert [r[:2] for r in rows_of(result, f"{JAVA}/OrderController.java")] == [
        ["GET", "/orders"],
        ["POST", "/orders"],
        ["GET", "/orders/{id:[0-9]+}"],
    ]
    l3 = section(result, f"{JAVA}/OrderController.java").l3_md
    assert "| sku | String | yes |" in l3 and "| qty | int | no |" in l3
    assert "serialVersionUID" not in l3


def test_spring_dynamic_path_partial(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        """package app;
@RestController
public class C {
  @GetMapping("/ok")
  void ok() {}
  @GetMapping(Paths.USERS)
  void users() {}
  @GetMapping(BASE + "/x")
  void concat() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/ok")]
    assert row(result).status == "partial"
    assert row(result).detail == f"{JAVA}/C.java:6; {JAVA}/C.java:8"


def test_spring_dynamic_class_prefix_partial(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        'package app;\n@RestController\n@RequestMapping(Api.BASE)\npublic class C {\n  @GetMapping("/x") void x() {}\n}\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == []
    assert (row(result).status, row(result).detail) == ("partial", f"{JAVA}/C.java:3")


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        (
            "src/main/resources/application.properties",
            "server.servlet.context-path=/api\n",
        ),
        (
            "src/main/resources/application-prod.properties",
            "spring.mvc.servlet.path = /v1\n",
        ),
        (
            "src/main/resources/application.yml",
            "server:\n  port: 80\n  servlet:\n    context-path: /api\n",
        ),
        (
            "src/main/resources/application.yaml",
            "spring:\n  mvc:\n    servlet:\n      path: /api\n",
        ),
        (
            "src/main/resources/application.properties",
            "server.servlet.contextPath=/api\n",
        ),
    ],
)
def test_spring_context_path_config_is_a_site(tmp_path, rel, text):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @GetMapping("/x") void x() {} }\n',
    )
    write(tmp_path, rel, text)
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail.startswith(rel + ":")


def test_spring_harmless_config_is_not_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @GetMapping("/x") void x() {} }\n',
    )
    write(
        tmp_path,
        "src/main/resources/application.yml",
        "server:\n  port: 8080\n  servlet:\n    context-path: /\nspring:\n  application:\n    name: x\n",
    )
    assert row(run_routes(tmp_path)).status == "complete"


def test_spring_functional_router_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/R.java",
        """package app;
@Configuration
class R {
  @Bean
  RouterFunction<ServerResponse> r(H h) {
    return RouterFunctions.route().GET("/x", h::get).build();
  }
}
""",
    )
    write(
        tmp_path,
        f"{KOTLIN}/K.kt",
        'package app\nfun routes(h: H) = coRouter { GET("/y", h::get) }\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    detail = row(result).detail
    assert f"{JAVA}/R.java:5" in detail and f"{KOTLIN}/K.kt:2" in detail


def test_spring_non_controller_mapping_is_a_site_but_feign_is_not(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/UserClient.java",
        '@FeignClient(name = "users")\ninterface UserClient {\n  @GetMapping("/u/{id}") User get(@PathVariable Long id);\n}\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).detail == "build.gradle:2"
    write(
        tmp_path,
        f"{JAVA}/Base.java",
        'abstract class Base {\n  @GetMapping("/inherited") void x() {}\n}\n',
    )
    again = run_routes(tmp_path)
    assert row(again).status == "partial" and row(again).detail == f"{JAVA}/Base.java:2"


def test_spring_composed_annotation_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/Api.java",
        '@RestController\n@RequestMapping("/api/v1")\n@Retention(RetentionPolicy.RUNTIME)\npublic @interface ApiV1 {}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@ApiV1\nclass C {\n  @GetMapping("/x") void x() {}\n}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert f"{JAVA}/C.java:1" in row(result).detail


def test_spring_kotlin_controller(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/ItemController.kt",
        """package app
@RestController
@RequestMapping(value = ["/items"])
class ItemController(private val svc: ItemService) {
  @GetMapping("/{id}")
  fun get(@PathVariable id: Long): Item = svc.get(id)

  @PostMapping
  fun create(@Valid @RequestBody body: CreateItem): Item = svc.create(body)

  @RequestMapping(path = ["/x", "/y"], method = [RequestMethod.DELETE])
  fun remove() {}

  @GetMapping(Paths.ALL)
  fun all() = 1
}
data class CreateItem(val name: String, val note: String?, val qty: Int = 1)
""",
    )
    result = run_routes(tmp_path)
    file = f"{KOTLIN}/ItemController.kt"
    assert rows_of(result, file) == [
        ["POST", "/items", "ItemController.create", file, "CreateItem"],
        ["DELETE", "/items/x", "ItemController.remove", file, ""],
        ["DELETE", "/items/y", "ItemController.remove", file, ""],
        ["GET", "/items/{id}", "ItemController.get", file, ""],
    ]
    l3 = section(result, file).l3_md
    assert "| name | String | yes |" in l3
    assert "| note | String? | no |" in l3
    assert "| qty | Int | no |" in l3
    assert row(result).status == "partial" and row(result).detail == f"{file}:14"


def test_request_type_outside_repo_has_no_fields(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @PostMapping("/x") void x(@RequestBody Map<String, Object> m, @RequestBody Ext e) {} }\n',
    )
    result = run_routes(tmp_path)
    assert (
        "Map<String, Object>: request type declared outside the repo"
        in section(result, f"{JAVA}/C.java").l3_md
    )


def test_type_cells_never_carry_an_annotation_value(tmp_path):
    gradle(tmp_path, MICRONAUT)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        """
@Controller("/c") class C {
  @Post("/m") void m(@Body Map<String, @Size(max = 987654312) String> m) {}
  @Post("/d") void d(@Body Dto d) {}
}
class Dto { java.util.List<@Size(max = 987654329) String> tags; String name; }
""",
    )
    result = run_routes(tmp_path)
    sec = section(result, f"{JAVA}/C.java")
    blob = sec.l2_md + sec.l3_md
    assert "98765431" not in blob and "98765432" not in blob and "@Size" not in blob
    assert "| tags | java.util.List<String> | no |" in sec.l3_md
    assert "Map<String, String>" in sec.l2_md


def test_request_type_list_unwraps_to_element(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @PostMapping("/x") void x(@RequestBody List<Dto> m) {} }\nclass Dto { @NotEmpty String a; Integer b; }\n',
    )
    l3 = section(run_routes(tmp_path), f"{JAVA}/C.java").l3_md
    assert "| a | String | yes |" in l3 and "| b | Integer | no |" in l3


# --- Quarkus ----------------------------------------------------------------


def test_quarkus_class_and_method_path(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/FruitResource.java",
        """package app;
@Path("/fruits")
@Produces(MediaType.APPLICATION_JSON)
@ApplicationScoped
public class FruitResource {
  @GET
  public List<Fruit> list() { return null; }
  @GET
  @Path("/{id}")
  public Fruit one(@PathParam("id") Long id) { return null; }
  @POST
  @Transactional
  public Response add(@Valid Fruit f) { return null; }
  @DELETE @Path("{id}")
  public void del(@PathParam("id") Long id) {}
}
""",
    )
    result = run_routes(tmp_path)
    file = f"{JAVA}/FruitResource.java"
    assert rows_of(result, file) == [
        ["GET", "/fruits", "FruitResource.list", file, ""],
        ["POST", "/fruits", "FruitResource.add", file, ""],
        ["DELETE", "/fruits/{id}", "FruitResource.del", file, ""],
        ["GET", "/fruits/{id}", "FruitResource.one", file, ""],
    ]
    assert row(result).status == "complete"


def test_quarkus_application_path_prefixes_routes(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/App.java",
        '@ApplicationPath("/api")\npublic class App extends Application {}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/R.java",
        '@Path("r") public class R { @GET public String g() { return ""; } }\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/api/r")]
    assert row(result).status == "complete"


def test_quarkus_dynamic_paths_and_locator_partial(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/R.java",
        """@Path("/r")
public class R {
  @GET @Path(Consts.X) public String a() { return ""; }
  @Path("/sub") public Sub sub() { return null; }
  @GET public String ok() { return ""; }
}
""",
    )
    write(
        tmp_path,
        f"{JAVA}/Dyn.java",
        '@Path(Consts.BASE)\npublic class Dyn { @GET public String a() { return ""; } }\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/r")]
    assert row(result).status == "partial"
    assert row(result).detail == f"{JAVA}/Dyn.java:1; {JAVA}/R.java:3; {JAVA}/R.java:4"


@pytest.mark.parametrize(
    "text",
    [
        "quarkus.http.root-path=/api\n",
        "%prod.quarkus.http.root-path=/api\n",
        "quarkus.rest.path=/x\n",
        "quarkus:\n  http:\n    root-path: /api\n",
    ],
)
def test_quarkus_root_path_config_is_a_site(tmp_path, text):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/R.java",
        '@Path("/r") public class R { @GET public String a() { return ""; } }\n',
    )
    name = (
        "application.yml"
        if ":" in text.splitlines()[0] and "=" not in text
        else "application.properties"
    )
    write(tmp_path, f"src/main/resources/{name}", text)
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail.startswith(f"src/main/resources/{name}:")


def test_quarkus_rest_client_is_not_a_server_route(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/Client.java",
        '@RegisterRestClient(configKey = "x")\n@Path("/remote")\npublic interface Client { @GET String get(); }\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).detail == "build.gradle:2"


def test_quarkus_reactive_routes_are_a_site(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/H.java",
        '@ApplicationScoped\npublic class H {\n  @Route(path = "/hi", methods = HttpMethod.GET)\n  void hi(RoutingContext rc) {}\n}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial" and row(result).detail == f"{JAVA}/H.java:3"


def test_quarkus_kotlin_resource(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{KOTLIN}/R.kt",
        """package app
@Path("/books")
@RolesAllowed("user")
class BookResource {
  @GET
  @Path("/{isbn}")
  fun one(@PathParam("isbn") isbn: String): Book = TODO()

  @POST
  fun add(book: Book): Response = TODO()
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/books/{isbn}"), ("POST", "/books")]
    assert row(result).status == "complete"


# --- Micronaut --------------------------------------------------------------


def test_micronaut_controller_prefix_and_body(tmp_path):
    gradle(tmp_path, MICRONAUT)
    write(
        tmp_path,
        f"{JAVA}/PetController.java",
        """package app;
@Controller("/pets")
@Secured(SecurityRule.IS_AUTHENTICATED)
@ExecuteOn(TaskExecutors.BLOCKING)
public class PetController {
  @Get("/{id}")
  public Pet get(@PathVariable Long id) { return null; }
  @Post
  public HttpResponse<Pet> save(@Body @Valid PetForm form) { return null; }
  @Put(uri = "/{id}", produces = MediaType.APPLICATION_JSON)
  Pet put() { return null; }
  @Delete("/{id}") void del() {}
  @Get void list() {}
}
@Introspected
class PetForm { @NotBlank String name; Integer age; }
""",
    )
    result = run_routes(tmp_path)
    file = f"{JAVA}/PetController.java"
    assert rows_of(result, file) == [
        ["GET", "/pets", "PetController.list", file, ""],
        ["POST", "/pets", "PetController.save", file, "PetForm"],
        ["DELETE", "/pets/{id}", "PetController.del", file, ""],
        ["GET", "/pets/{id}", "PetController.get", file, ""],
        ["PUT", "/pets/{id}", "PetController.put", file, ""],
    ]
    l3 = section(result, file).l3_md
    assert "| name | String | yes |" in l3 and "| age | Integer | no |" in l3
    assert row(result).status == "complete"


def test_micronaut_kotlin_and_bare_controller(tmp_path):
    gradle(tmp_path, MICRONAUT)
    write(
        tmp_path,
        f"{KOTLIN}/Hello.kt",
        """package app
@Controller
class Root {
  @Get("/health") fun health() = "ok"
}

@Controller("/hello")
@Secured(SecurityRule.IS_ANONYMOUS)
class Hello {
  @Get("/{name}{?lang}")
  suspend fun greet(name: String, lang: String?): HttpResponse<String> = TODO()
  @Post("/")
  fun add(@Body req: Greeting) = 1
}
data class Greeting(val text: String, val lang: String? = null)
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [
        ("GET", "/health"),
        ("GET", "/hello/{name}"),
        ("POST", "/hello"),
    ]
    assert row(result).status == "complete"
    assert "| text | String | yes |" in section(result, f"{KOTLIN}/Hello.kt").l3_md


def test_micronaut_dynamic_path_and_context_path_partial(tmp_path):
    gradle(tmp_path, MICRONAUT)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@Controller("/c")\nclass C {\n  @Get(Paths.X) void a() {}\n  @CustomHttpMethod(method = "PURGE", value = "/p") void b() {}\n  @Get("/ok") void ok() {}\n}\n',
    )
    write(
        tmp_path,
        "src/main/resources/application.yml",
        "micronaut:\n  server:\n    context-path: /api\n",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/c/ok")]
    assert row(result).status == "partial"
    assert row(result).detail == (
        f"{JAVA}/C.java:3; {JAVA}/C.java:4; src/main/resources/application.yml:3"
    )


def test_micronaut_declarative_client_is_not_a_route(tmp_path):
    gradle(tmp_path, MICRONAUT)
    write(
        tmp_path,
        f"{JAVA}/Api.java",
        '@Client("/remote")\npublic interface Api { @Get("/x") String x(); }\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).detail == "build.gradle:2"


def test_syntax_error_in_controller_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @GetMapping("/x") void x( {} \n',
    )
    assert row(run_routes(tmp_path)).status == "partial"


def test_jvm_output_is_deterministic(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @GetMapping("/b") void b() {} @GetMapping("/a") void a() {} }\n',
    )
    assert run_routes(tmp_path) == run_routes(tmp_path)


# --- symbols ----------------------------------------------------------------


def names_of(result, slug: str = "sym.root") -> list[tuple[str, str]]:
    (sec,) = [s for s in result.sections if s.id == slug]
    return sorted((r[0], r[1]) for r in table_rows(sec.l2_md)[1:])


def test_java_symbols_public_surface(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/Limits.java",
        """package app;
public class Limits {
  public static final int MAX = 10;
  public static final String API_KEY = "sk-live-abc123secret";
  static final int HIDDEN = 1;
  public final int inst = 2;
  private static final int P = 3;
  public static int mutable = 4;
}
class PackagePrivate { public static final int NOPE = 1; }
public interface Shape { int SIDES = 4; void draw(); }
public enum Color { RED("#f00"), GREEN("#0f0"); Color(String hex) {} }
public record Point(int x, int y) {}
public @interface Marker {}
""",
    )
    result = run_symbols(tmp_path)
    assert names_of(result) == sorted(
        [
            ("Limits", "class"),
            ("Limits.MAX", "member"),
            ("Limits.API_KEY", "member"),
            ("Shape", "interface"),
            ("Shape.SIDES", "member"),
            ("Color", "enum"),
            ("Color.RED", "member"),
            ("Color.GREEN", "member"),
            ("Point", "class"),
            ("Marker", "interface"),
        ]
    )
    (cov,) = [r for r in result.coverage if r.framework == "java"]
    assert cov.status == "complete"
    blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
    assert "sk-live-abc123secret" not in blob and "#f00" not in blob


def test_kotlin_symbols_public_surface(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/Model.kt",
        """package app
class Account(val id: Long)
internal class Hidden
private fun secret() {}
fun open() {}
val DEFAULT_NAME = "x"
const val TOKEN = "sk-live-abc"
object Config {
  const val SECRET = "sk-live-zzz"
  val lazyVal = 1
  private const val P = 1
}
enum class Role(val label: String) { ADMIN("a"), USER("u") }
interface Repo
typealias Id = Long
sealed class Result
class Owner {
  companion object {
    const val ANSWER = 42
  }
}
private object Priv {
  const val Q = 1
}
""",
    )
    result = run_symbols(tmp_path)
    assert names_of(result) == sorted(
        [
            ("Account", "class"),
            ("open", "function"),
            ("DEFAULT_NAME", "const"),
            ("TOKEN", "const"),
            ("Config", "class"),
            ("Config.SECRET", "member"),
            ("Role", "enum"),
            ("Role.ADMIN", "member"),
            ("Role.USER", "member"),
            ("Repo", "interface"),
            ("Id", "type"),
            ("Result", "class"),
            ("Owner", "class"),
            ("Owner.ANSWER", "member"),
        ]
    )
    (cov,) = [r for r in result.coverage if r.framework == "kotlin"]
    assert cov.status == "complete"
    blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
    assert "sk-live" not in blob


def test_jvm_symbols_syntax_error_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/Bad.java",
        "public class Bad { public static final int X = ; \n",
    )
    (cov,) = [r for r in run_symbols(tmp_path).coverage if r.framework == "java"]
    assert cov.status == "partial" and f"{JAVA}/Bad.java:" in cov.detail


# --- more edge cases --------------------------------------------------------


def test_test_source_sets_are_not_product_routes(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        "src/test/java/app/FakeController.java",
        '@RestController class FakeController { @GetMapping("/fake") void f() {} }\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).detail == "build.gradle:2"


def test_spring_computed_method_and_class_verb_filter_are_sites(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/A.java",
        '@RestController\nclass A {\n  @RequestMapping(value = "/m", method = Verbs.X)\n  void m() {}\n}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/B.java",
        '@RestController\n@RequestMapping(value = "/b", method = RequestMethod.GET)\nclass B {\n  @GetMapping("/x") void x() {}\n}\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == []
    assert row(result).detail == f"{JAVA}/A.java:3; {JAVA}/B.java:2"


def test_quarkus_two_application_paths_are_sites(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/A.java",
        '@ApplicationPath("/a")\nclass A extends Application {}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/B.java",
        '@ApplicationPath("/b")\nclass B extends Application {}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/R.java",
        '@Path("/r") class R { @GET String g() { return ""; } }\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/r")]
    assert row(result).detail == f"{JAVA}/A.java:1; {JAVA}/B.java:1"


def test_java_and_kotlin_controllers_share_a_scope(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/J.java",
        '@RestController class J { @GetMapping("/j") void j() {} }\n',
    )
    write(
        tmp_path,
        f"{KOTLIN}/K.kt",
        '@RestController\nclass K {\n  @GetMapping("/k")\n  fun k() {}\n}\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/j"), ("GET", "/k")]
    assert row(result).status == "complete"


def test_kotlin_request_type_with_base_class_has_no_fields(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/K.kt",
        '@RestController\nclass K {\n  @PostMapping("/k")\n  fun k(@RequestBody b: Req) {}\n}\nclass Req(val a: String) : Base()\n',
    )
    l3 = section(run_routes(tmp_path), f"{KOTLIN}/K.kt").l3_md
    assert "Req: request type declared outside the repo" in l3


# --- fix round 1 ------------------------------------------------------------


def detail_sites(result) -> list[str]:
    return [s for s in row(result).detail.split("; ") if s]


def test_controller_with_no_route_and_no_site_gets_a_class_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/Empty.java",
        "package app;\n@RestController\npublic class Empty {\n}\n",
    )
    result = run_routes(tmp_path)
    assert result.sections == []
    assert (row(result).status, row(result).detail) == (
        "partial",
        f"{JAVA}/Empty.java:3",
    )


def test_spring_interface_implementation_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/UserApi.java",
        'package app;\n@RequestMapping("/api/users")\npublic interface UserApi {\n  @GetMapping("/{id}")\n  UserDto get(@PathVariable Long id);\n}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/UserController.java",
        "package app;\n@RestController\npublic class UserController implements UserApi {\n  @Override\n  public UserDto get(Long id) { return null; }\n}\n",
    )
    result = run_routes(tmp_path)
    assert result.sections == []
    assert row(result).status == "partial"
    assert detail_sites(result) == [
        f"{JAVA}/UserApi.java:2",
        f"{JAVA}/UserApi.java:4",
        f"{JAVA}/UserController.java:5",
    ]


def test_override_in_controller_is_a_site_even_beside_real_routes(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        'package app;\n@RestController\npublic class C implements Api {\n  @GetMapping("/x") public String x() { return ""; }\n  @Override\n  public String y() { return ""; }\n}\n',
    )
    write(
        tmp_path,
        f"{KOTLIN}/K.kt",
        'package app\n\n@RestController\nclass K : PetsApi {\n    override fun listPets(): String = ""\n}\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/x")]
    assert detail_sites(result) == [f"{JAVA}/C.java:6", f"{KOTLIN}/K.kt:5"]


def test_quarkus_resource_implementing_interface_is_a_site(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/R.java",
        '@Path("/r")\npublic class R implements RApi {\n  @Override\n  public String g() { return ""; }\n}\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).status == "partial"


@pytest.mark.parametrize(
    "line",
    [
        "id 'org.openapi.generator' version '7.0.0'",
        "id 'io.quarkiverse.openapi.generator' version '2.0'",
        "implementation 'io.swagger:swagger-codegen:3'",
    ],
)
def test_openapi_generator_in_build_file_is_a_site(tmp_path, line):
    write(
        tmp_path,
        "build.gradle",
        f"plugins {{\n  {line}\n}}\ndependencies {{\n  implementation '{SPRING}'\n}}\n",
    )
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @GetMapping("/x") void x() {} }\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert detail_sites(result) == ["build.gradle:2"]


@pytest.mark.parametrize(
    ("kind", "base"),
    [
        ("interface", '@RequestMapping("/api")\npublic interface Base {}\n'),
        ("abstract", '@RequestMapping("/api")\npublic abstract class Base {}\n'),
    ],
)
def test_class_level_prefix_on_a_non_controller_is_a_site(tmp_path, kind, base):
    gradle(tmp_path, SPRING)
    write(tmp_path, f"{JAVA}/Base.java", "package app;\n" + base)
    write(
        tmp_path,
        f"{JAVA}/UserController.java",
        "package app;\n@RestController\npublic class UserController "
        + ("implements" if kind == "interface" else "extends")
        + ' Base {\n  @GetMapping("/users")\n  public String list() { return ""; }\n}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert f"{JAVA}/Base.java:2" in row(result).detail


def test_composed_annotation_only_files_are_still_scanned(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/ApiV1.java",
        '@RestController\n@RequestMapping("/api/v1")\npublic @interface ApiV1 {}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/GetJson.java",
        '@GetMapping(produces = "application/json")\npublic @interface GetJson {}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/Users.java",
        'package app;\n@ApiV1\npublic class Users {\n  @GetJson("/users")\n  public String list() { return ""; }\n}\n',
    )
    write(
        tmp_path,
        f"{KOTLIN}/Api.kt",
        "package app\n\n@RestController\nannotation class KApi\n",
    )
    write(
        tmp_path,
        f"{KOTLIN}/Ku.kt",
        'package app\n\n@KApi\nclass Ku {\n    fun u() = "u"\n}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert f"{JAVA}/Users.java:2" in row(result).detail
    assert f"{JAVA}/Users.java:4" in row(result).detail
    assert f"{KOTLIN}/Ku.kt:3" in row(result).detail


@pytest.mark.parametrize(
    ("fw", "text"),
    [
        (
            SPRING,
            '@RestController\n@RequestMapping("${api.prefix}/orders")\nclass C { @GetMapping("/x") void x() {} }\n',
        ),
        (
            SPRING,
            '@RestController\nclass C {\n  @GetMapping("${p.x:/x}") void x() {}\n}\n',
        ),
        (
            MICRONAUT,
            '@Controller("${api.base:/api}/health")\nclass C {\n  @Get void h() {}\n}\n',
        ),
    ],
)
def test_placeholder_path_is_a_site_not_a_route(tmp_path, fw, text):
    gradle(tmp_path, fw)
    write(tmp_path, f"{JAVA}/C.java", text)
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).status == "partial"


def test_path_literal_escapes_are_decoded(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C {\n  @GetMapping("/{id:\\\\d+}") void a() {}\n}\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/{id:\\d+}")]


def test_micronaut_query_templates_are_stripped(tmp_path):
    gradle(tmp_path, MICRONAUT)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@Controller("/c")\nclass C {\n  @Get("/list{?max,offset}") void a() {}\n  @Get("/{id}{&x}") void b() {}\n}\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/c/list"), ("GET", "/c/{id}")]


def test_request_type_fields_come_from_the_routes_own_language(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/U.java",
        'package app;\n@RestController\nclass U {\n  @PostMapping("/u") void c(@RequestBody Req r) {}\n}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/Req.java",
        "package app;\npublic record Req(String email) {}\n",
    )
    write(tmp_path, "frontend/package.json", '{"dependencies": {"react": "18"}}')
    write(
        tmp_path,
        "frontend/src/types.ts",
        "export interface Req { displayName?: string }\n",
    )
    l3 = section(run_routes(tmp_path), f"{JAVA}/U.java").l3_md
    assert "| email | String | yes |" in l3 and "displayName" not in l3


def test_java_reader_does_not_answer_for_a_typescript_route(tmp_path):
    from strata_kb.codeingest.extractors import _jvm_fields

    write(tmp_path, "src/Req.java", "public record Req(String email) {}\n")
    assert (
        _jvm_fields.declared_fields(tmp_path, ["src/Req.java", "a.ts"], "Req", "a.ts")
        is None
    )


def test_spring_boot_jersey_resource_is_a_site(tmp_path):
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-jersey")
    write(
        tmp_path,
        f"{JAVA}/H.java",
        'package app;\n@Component\n@Path("/hello")\npublic class H {\n  @GET public String h() { return ""; }\n}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).detail == f"{JAVA}/H.java:3"


def test_spring_data_rest_repositories_are_sites_only_with_the_dependency(tmp_path):
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-data-rest")
    write(
        tmp_path,
        f"{JAVA}/PersonRepository.java",
        "package app;\npublic interface PersonRepository\n    extends JpaRepository<Person, Long> {\n}\n",
    )
    write(
        tmp_path,
        f"{KOTLIN}/PetRepository.kt",
        "package app\n\ninterface PetRepository : CrudRepository<Pet, Long>\n",
    )
    result = run_routes(tmp_path)
    assert detail_sites(result) == [
        f"{JAVA}/PersonRepository.java:2",
        f"{KOTLIN}/PetRepository.kt:3",
    ]
    plain = tmp_path / "plain"
    gradle(plain, SPRING)
    write(
        plain,
        f"{JAVA}/PersonRepository.java",
        "package app;\npublic interface PersonRepository extends JpaRepository<Person, Long> {}\n",
    )
    write(plain, f"{JAVA}/C.java", CONTROLLER)
    assert row(run_routes(plain)).status == "complete"


def test_spring_http_exchange_on_a_controller_is_listed(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/G.java",
        """package app;
@RestController
@HttpExchange("/greet")
public class G {
  @GetExchange("/{name}")
  public String greet(@PathVariable String name) { return name; }
  @PostExchange
  public void add(@RequestBody Msg m) {}
  @HttpExchange(method = "PUT", url = "/p")
  public void put() {}
}
""",
    )
    write(
        tmp_path,
        f"{JAVA}/Client.java",
        'package app;\n@HttpExchange("/remote")\npublic interface Client {\n  @GetExchange("/x") String x();\n}\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [
        ("GET", "/greet/{name}"),
        ("POST", "/greet"),
        ("PUT", "/greet/p"),
    ]
    assert row(result).status == "complete"


def test_quarkus_spring_web_controller_is_a_site(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/S.java",
        'package app;\n@RestController\n@RequestMapping("/s")\npublic class S {\n  @GetMapping("/x") public String x() { return ""; }\n}\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).status == "partial"
    assert f"{JAVA}/S.java:2" in row(result).detail


def test_kotlin_one_line_bodies_do_not_make_a_controller_partial(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/C.kt",
        """package app

@RestController
@RequestMapping("/c")
class C {
    companion object { private val log = LoggerFactory.getLogger(C::class.java) }

    @GetMapping("/ok")
    fun ok(): String {
        return "ok"
    }
}

object Paths { const val X = "/x" }

data class P(val a: Int) { fun b() = a }
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/c/ok")]
    assert (row(result).status, row(result).detail) == ("complete", "")


def test_kotlin_handler_inside_a_one_line_body_is_still_found(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/C.kt",
        'package app\n\n@RestController\nclass C { @GetMapping("/a") fun a() {} }\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/a")]
    assert row(result).status == "complete"


def test_kotlin_one_line_object_symbols_are_read(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/P.kt",
        'package app\n\nobject Paths { const val X = "/x" }\n\nclass K { fun f() {} }\n',
    )
    result = run_symbols(tmp_path)
    assert ("Paths.X", "member") in names_of(result)
    (cov,) = [r for r in result.coverage if r.framework == "kotlin"]
    assert cov.status == "complete"


def test_product_files_named_like_tests_are_scanned(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/ABTest.java",
        'package app;\n@RestController\npublic class ABTest {\n  @GetMapping("/ab")\n  public String ab() { return ""; }\n}\n',
    )
    write(
        tmp_path,
        f"{KOTLIN}/ProductSpec.kt",
        'package app\n\n@RestController\nclass ProductSpec {\n    @GetMapping("/spec")\n    fun s() = ""\n}\n',
    )
    write(
        tmp_path,
        "src/test/java/app/FooTest.java",
        '@RestController class FooTest { @GetMapping("/t") void t() {} }\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/ab"), ("GET", "/spec")]


def test_request_type_sources_are_read_once_per_run(tmp_path, monkeypatch):
    from strata_kb.codeingest.extractors import _jvm_fields

    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        'package app;\n@RestController\nclass C {\n  @PostMapping("/a") void a(@RequestBody A a) {}\n  @PostMapping("/b") void b(@RequestBody B b) {}\n}\n',
    )
    write(tmp_path, f"{JAVA}/A.java", "package app;\nclass A { String a; }\n")
    write(tmp_path, f"{JAVA}/B.java", "package app;\nclass B { String b; }\n")
    seen: list[str] = []
    real = _jvm_fields._read
    monkeypatch.setattr(
        _jvm_fields, "_read", lambda root, rel: (seen.append(rel), real(root, rel))[1]
    )
    run_routes(tmp_path)
    assert seen and len(seen) == len(set(seen))


def test_kotlin_controller_survives_the_grammar_misparse(tmp_path):
    # tree-sitter-kotlin reads `@A @B("x") class C {}` as an expression when
    # another top-level declaration follows; the file must still be read
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/C.kt",
        """package app

@RestController
@RequestMapping("/c")
class C {
    @GetMapping("/ok")
    fun ok() = "ok"
}

data class Dto(val a: String)

fun helper() {
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/c/ok")]
    assert (row(result).status, row(result).detail) == ("complete", "")
    symbols_result = run_symbols(tmp_path)
    assert {"C", "Dto", "helper"} <= {n for n, _k in names_of(symbols_result)}


def test_kotlin_misparse_that_cannot_be_repaired_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/C.kt",
        'package app\n\n@RestController\n@RequestMapping("/c")\nclass C {\n    @GetMapping("/ok") fun ok() = (\n}\n\nclass D {\n}\n',
    )
    assert row(run_routes(tmp_path)).status == "partial"


# --- fix round 2 ------------------------------------------------------------

CONTROLLER = '@RestController class C { @GetMapping("/x") void x() {} }\n'


def test_generator_in_a_sibling_module_marks_every_route_scope(tmp_path):
    write(tmp_path, "settings.gradle", "include 'api', 'app'\n")
    write(
        tmp_path,
        "api/build.gradle",
        "plugins { id 'org.openapi.generator' version '7.0.0' }\n",
    )
    gradle(tmp_path, SPRING, "app")
    write(tmp_path, f"app/{JAVA}/C.java", CONTROLLER)
    result = run_routes(tmp_path)
    assert row(result, "app").status == "partial"
    assert row(result, "app").detail == "api/build.gradle:1"


def test_generator_in_a_parent_pom_marks_the_module(tmp_path):
    write(
        tmp_path,
        "pom.xml",
        "<project>\n<build><plugins>\n<plugin>\n<artifactId>openapi-generator-maven-plugin</artifactId>\n</plugin>\n</plugins></build>\n</project>\n",
    )
    write(
        tmp_path,
        "app/pom.xml",
        "<project><dependencies><dependency><artifactId>spring-boot-starter-web</artifactId></dependency></dependencies></project>\n",
    )
    write(tmp_path, f"app/{JAVA}/C.java", CONTROLLER)
    assert row(run_routes(tmp_path), "app").detail == "pom.xml:4"


def test_openapi_client_only_dependency_is_not_a_generator(tmp_path):
    write(
        tmp_path,
        "build.gradle",
        f"dependencies {{\n  implementation '{SPRING}'\n  implementation 'org.openapitools:jackson-databind-nullable:0.2.6'\n}}\n",
    )
    write(tmp_path, f"{JAVA}/C.java", CONTROLLER)
    assert row(run_routes(tmp_path)).status == "complete"


def test_framework_scope_with_no_routes_and_no_sites_gets_a_manifest_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(tmp_path, f"{JAVA}/S.java", "package app;\n@Service\npublic class S {}\n")
    result = run_routes(tmp_path)
    assert result.sections == []
    assert (row(result).status, row(result).detail) == ("partial", "build.gradle:2")


def test_quarkus_class_implementing_an_interface_from_another_module(tmp_path):
    write(tmp_path, "settings.gradle", "include 'api', 'app'\n")
    write(
        tmp_path,
        f"api/{JAVA}/GreetingApi.java",
        'package app;\n@Path("/greetings")\npublic interface GreetingApi {\n  @GET @Path("/{name}") String greet(String name);\n}\n',
    )
    gradle(tmp_path, QUARKUS, "app")
    write(
        tmp_path,
        f"app/{JAVA}/GreetingResource.java",
        "package app;\npublic class GreetingResource implements org.acme.api.GreetingApi {\n  public String greet(String name) { return name; }\n}\n",
    )
    result = run_routes(tmp_path)
    assert row(result, "app").status == "partial"
    assert row(result, "app").detail == f"app/{JAVA}/GreetingResource.java:2"


def test_quarkus_interface_in_the_same_scope_is_listed_once(tmp_path):
    gradle(tmp_path, QUARKUS)
    write(
        tmp_path,
        f"{JAVA}/GreetingApi.java",
        'package app;\n@Path("/g")\npublic interface GreetingApi {\n  @GET String greet();\n}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/GreetingResource.java",
        'package app;\npublic class GreetingResource implements GreetingApi {\n  public String greet() { return ""; }\n}\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/g")]
    assert row(result).status == "complete"


def test_kotlin_application_class_followed_by_main_is_read(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/BlogApplication.kt",
        """package app

import org.springframework.boot.runApplication

@SpringBootApplication
@EnableConfigurationProperties(BlogProperties::class)
class BlogApplication

fun main(args: Array<String>) {
    runApplication<BlogApplication>(*args)
}
""",
    )
    result = run_symbols(tmp_path)
    assert {"BlogApplication", "main"} <= {n for n, _k in names_of(result)}
    (cov,) = [r for r in result.coverage if r.framework == "kotlin"]
    assert (cov.status, cov.detail) == ("complete", "")


def test_type_field_cache_does_not_outlive_the_run(tmp_path):
    from strata_kb.codeingest.extractors import _jvm_fields

    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        '@RestController class C { @PostMapping("/a") void a(@RequestBody A a) {} }\nclass A { String a; }\n',
    )
    run_routes(tmp_path)
    assert _jvm_fields._reads is None


def test_spring_request_mapping_and_http_exchange_prefix_together_is_a_site(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{JAVA}/C.java",
        'package app;\n@RestController\n@RequestMapping("/a")\n@HttpExchange("/b")\nclass C {\n  @GetMapping("/x") void x() {}\n}\n',
    )
    result = run_routes(tmp_path)
    assert result.sections == [] and row(result).status == "partial"


# --- fix round 3 ------------------------------------------------------------


def test_non_web_spring_boot_module_gets_no_framework_net_site(tmp_path):
    write(tmp_path, "settings.gradle", "include 'common', 'web'\n")
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-data-jpa", "common")
    write(
        tmp_path,
        f"common/{JAVA}/User.java",
        "package app;\n@Entity\npublic class User {}\n",
    )
    write(
        tmp_path,
        "pom-module/pom.xml",
        "<project><dependencies><dependency><artifactId>spring-boot-starter-validation</artifactId></dependency></dependencies></project>\n",
    )
    write(tmp_path, f"pom-module/{JAVA}/V.java", "package app;\npublic class V {}\n")
    gradle(tmp_path, SPRING, "web")
    result = run_routes(tmp_path)
    assert (row(result, "common").status, row(result, "common").detail) == (
        "complete",
        "",
    )
    assert (row(result, "pom-module").status, row(result, "pom-module").detail) == (
        "complete",
        "",
    )
    assert (row(result, "web").status, row(result, "web").detail) == (
        "partial",
        "web/build.gradle:2",
    )


def test_quarkus_net_site_lands_on_the_server_dependency(tmp_path):
    write(
        tmp_path,
        "pom.xml",
        "<project>\n<properties>\n<quarkus.platform.version>3.0</quarkus.platform.version>\n</properties>\n"
        "<dependencyManagement><dependencies><dependency><artifactId>quarkus-bom</artifactId></dependency></dependencies></dependencyManagement>\n"
        "<dependencies>\n<dependency><artifactId>quarkus-rest</artifactId></dependency>\n</dependencies>\n</project>\n",
    )
    write(tmp_path, f"{JAVA}/S.java", "package app;\npublic class S {}\n")
    assert row(run_routes(tmp_path)).detail == "pom.xml:7"


def test_kotlin_declaration_keyword_inside_a_comment_is_not_a_symbol(tmp_path):
    gradle(tmp_path, SPRING)
    write(
        tmp_path,
        f"{KOTLIN}/BlogApplication.kt",
        """package app

@SpringBootApplication
@EnableConfigurationProperties(BlogProperties::class)
class BlogApplication

/*
class Ghost
*/
fun main(args: Array<String>) {
    runApplication<BlogApplication>(*args)
}
""",
    )
    result = run_symbols(tmp_path)
    assert {n for n, _k in names_of(result)} == {"BlogApplication", "main"}


def test_quarkus_interface_name_with_regex_characters(tmp_path):
    write(tmp_path, "settings.gradle", "include 'api', 'app'\n")
    write(
        tmp_path,
        f"api/{JAVA}/Api.java",
        'package app;\n@Path("/g")\npublic interface Greeting$Api {\n  @GET String g();\n}\n',
    )
    gradle(tmp_path, QUARKUS, "app")
    write(
        tmp_path,
        f"app/{JAVA}/R.java",
        'package app;\npublic class R implements Greeting$Api {\n  public String g() { return ""; }\n}\n',
    )
    assert row(run_routes(tmp_path), "app").detail == f"app/{JAVA}/R.java:2"


def test_repo_wide_reads_happen_once_per_run(tmp_path, monkeypatch):
    from strata_kb.codeingest.extractors import _routes_jvm

    write(tmp_path, "settings.gradle", "include 'api', 'one', 'two'\n")
    write(tmp_path, "api/build.gradle", "plugins { id 'org.openapi.generator' }\n")
    write(
        tmp_path,
        f"api/{JAVA}/Api.java",
        'package app;\n@Path("/g")\npublic interface GreetingApi {\n  @GET String g();\n}\n',
    )
    for module in ("one", "two"):
        gradle(tmp_path, QUARKUS, module)
        write(
            tmp_path,
            f"{module}/{JAVA}/R.java",
            '@Path("/r") class R { @GET String g() { return ""; } }\n',
        )
    seen: list[str] = []
    real = _routes_jvm._read
    monkeypatch.setattr(
        _routes_jvm, "_read", lambda root, rel: (seen.append(rel), real(root, rel))[1]
    )
    run_routes(tmp_path)
    assert seen and len(seen) == len(set(seen))


# --- fix round 4 ------------------------------------------------------------

DELEGATE = (
    "package app;\n@Service\npublic class PetApiDelegateImpl implements PetApiDelegate {\n"
    '  public String get() { return ""; }\n}\n'
)


def test_web_dependency_inherited_from_the_parent_pom_is_a_site(tmp_path):
    write(
        tmp_path,
        "pom.xml",
        "<project><modules><module>app</module></modules>\n<dependencies>\n"
        "<dependency><artifactId>spring-boot-starter-web</artifactId></dependency>\n"
        "</dependencies></project>\n",
    )
    write(
        tmp_path,
        "app/pom.xml",
        "<project><parent><artifactId>p</artifactId></parent>\n<dependencies>"
        "<dependency><artifactId>spring-boot-starter-actuator</artifactId></dependency>"
        "</dependencies></project>\n",
    )
    write(tmp_path, f"app/{JAVA}/D.java", DELEGATE)
    cov = row(run_routes(tmp_path), "app")
    assert (cov.status, cov.detail) == ("partial", "pom.xml:3")


def test_spring_boot_4_webmvc_starter_is_a_server_dependency(tmp_path):
    write(
        tmp_path,
        "pom.xml",
        "<project><modules><module>app</module></modules>\n<dependencies>\n"
        "<dependency><artifactId>spring-boot-starter-webmvc</artifactId></dependency>\n"
        "</dependencies></project>\n",
    )
    write(
        tmp_path,
        "app/pom.xml",
        "<project><parent><artifactId>p</artifactId></parent>\n<dependencies>"
        "<dependency><artifactId>spring-boot-starter-actuator</artifactId></dependency>"
        "</dependencies></project>\n",
    )
    write(tmp_path, f"app/{JAVA}/D.java", DELEGATE)
    cov = row(run_routes(tmp_path), "app")
    assert (cov.status, cov.detail) == ("partial", "pom.xml:3")


def test_web_dependency_in_gradle_subprojects_block_is_a_site(tmp_path):
    write(tmp_path, "settings.gradle", "include 'app'\n")
    write(
        tmp_path,
        "build.gradle",
        f"subprojects {{\n  dependencies {{\n    implementation '{SPRING}'\n  }}\n}}\n",
    )
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-actuator", "app")
    write(tmp_path, f"app/{JAVA}/D.java", DELEGATE)
    cov = row(run_routes(tmp_path), "app")
    assert (cov.status, cov.detail) == ("partial", "build.gradle:3")


def test_micronaut_application_plugin_marks_a_web_module(tmp_path):
    write(
        tmp_path,
        "build.gradle.kts",
        'plugins { id("io.micronaut.application") version "4.2.1" }\n'
        'dependencies {\n  implementation("io.micronaut.serde:micronaut-serde-jackson")\n}\n',
    )
    write(
        tmp_path,
        f"{JAVA}/D.java",
        "package app;\n@Singleton\npublic class PetApiImpl implements PetApi {}\n",
    )
    cov = row(run_routes(tmp_path))
    assert (cov.status, cov.detail) == ("partial", "build.gradle.kts:1")


def test_micronaut_runtime_netty_marks_a_web_module(tmp_path):
    write(
        tmp_path,
        "build.gradle.kts",
        'dependencies {\n  implementation("io.micronaut:micronaut-inject")\n}\n'
        'micronaut {\n  runtime("netty")\n}\n',
    )
    write(tmp_path, f"{JAVA}/D.java", "package app;\npublic class PetApiImpl {}\n")
    cov = row(run_routes(tmp_path))
    assert (cov.status, cov.detail) == ("partial", "build.gradle.kts:5")


def test_version_catalog_alias_for_a_server_starter_is_a_site(tmp_path):
    write(
        tmp_path,
        "build.gradle.kts",
        "dependencies {\n"
        '  implementation("org.springframework.boot:spring-boot-starter-actuator")\n'
        "  implementation(libs.spring.boot.starter.web)\n}\n",
    )
    write(tmp_path, f"{JAVA}/D.java", DELEGATE)
    cov = row(run_routes(tmp_path))
    assert (cov.status, cov.detail) == ("partial", "build.gradle.kts:3")


def test_web_import_without_a_build_signal_is_a_site(tmp_path):
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-actuator")
    write(
        tmp_path,
        f"{JAVA}/D.java",
        "package app;\nimport org.springframework.http.ResponseEntity;\n"
        "@Service\npublic class D implements PetApiDelegate {}\n",
    )
    cov = row(run_routes(tmp_path))
    assert (cov.status, cov.detail) == ("partial", f"{JAVA}/D.java:2")


def test_data_module_without_web_imports_stays_complete(tmp_path):
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-data-jpa")
    write(
        tmp_path,
        f"{JAVA}/User.java",
        "package app;\nimport jakarta.persistence.Entity;\nimport jakarta.validation.constraints.NotNull;\n"
        "@Entity\npublic class User { @NotNull String name; }\n",
    )
    cov = row(run_routes(tmp_path))
    assert (cov.status, cov.detail) == ("complete", "")


@pytest.mark.parametrize(
    ("artifact", "manifest"),
    [
        ("quarkus-rest-client-jackson", "pom.xml"),
        ("quarkus-resteasy-client", "pom.xml"),
        ("quarkus-resteasy-reactive-client", "pom.xml"),
        ("spring-boot-starter-web-services", "pom.xml"),
    ],
)
def test_client_and_soap_artifacts_are_not_server_dependencies(
    tmp_path, artifact, manifest
):
    write(
        tmp_path,
        manifest,
        f"<project><dependencies><dependency><artifactId>{artifact}</artifactId>"
        "</dependency><dependency><artifactId>quarkus-arc</artifactId></dependency>"
        "<dependency><artifactId>spring-boot-starter-actuator</artifactId></dependency>"
        "</dependencies></project>\n",
    )
    write(tmp_path, f"{JAVA}/U.java", "package app;\npublic class U {}\n")
    result = run_routes(tmp_path)
    assert {(r.status, r.detail) for r in result.coverage} == {("complete", "")}


def test_inherited_data_rest_marks_repositories(tmp_path):
    write(tmp_path, "settings.gradle", "include 'app'\n")
    write(
        tmp_path,
        "build.gradle",
        "subprojects {\n  dependencies {\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-data-rest'\n  }\n}\n",
    )
    gradle(tmp_path, "org.springframework.boot:spring-boot-starter-actuator", "app")
    write(
        tmp_path,
        f"app/{JAVA}/R.java",
        "package app;\npublic interface PetRepository extends JpaRepository<Pet, Long> {}\n",
    )
    assert row(run_routes(tmp_path), "app").status == "partial"


def test_nested_run_does_not_clear_the_outer_runs_reads(tmp_path, monkeypatch):
    from strata_kb.codeingest.extractors import _routes_jvm

    outer, inner = tmp_path / "outer", tmp_path / "inner"
    write(outer, "settings.gradle", "include 'one', 'two'\n")
    for module in ("one", "two"):
        gradle(outer, QUARKUS, module)
        write(
            outer,
            f"{module}/{JAVA}/R.java",
            '@Path("/r") class R { @GET String g() { return ""; } }\n',
        )
    gradle(inner, QUARKUS)
    write(
        inner,
        f"{JAVA}/R.java",
        '@Path("/i") class R { @GET String g() {return "";} }\n',
    )
    seen: list[str] = []
    nested = []
    real = _routes_jvm._read

    def spy(root, rel):
        if root == outer:
            seen.append(rel)
            if rel.endswith("one/build.gradle") and not nested:
                nested.append(run_routes(inner))  # a second run, mid-way
        return real(root, rel)

    monkeypatch.setattr(_routes_jvm, "_read", spy)
    run_routes(outer)
    assert nested and seen and len(seen) == len(set(seen))
