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
    assert result.sections == [] and row(result).status == "complete"
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
    assert result.sections == [] and row(result).status == "complete"


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
        ("GET", "/hello/{name}{?lang}"),
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
    assert result.sections == [] and row(result).status == "complete"


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
    assert result.sections == [] and row(result).status == "complete"


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
