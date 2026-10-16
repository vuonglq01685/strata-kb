"""ASP.NET Core (C#): controller and minimal-API route adapter, the
`[FromBody]` request-type field reader, and the csharp exported symbols."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import routes, symbols
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows

WEB = '<Project Sdk="Microsoft.NET.Sdk.Web">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n  </PropertyGroup>\n</Project>\n'


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def web(root: Path, app: str = ".") -> None:
    write(root, f"{app}/Api.csproj" if app != "." else "Api.csproj", WEB)


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


def names_of(result) -> list[tuple[str, str]]:
    return sorted(
        (r[0], r[1]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )


# --- controllers ------------------------------------------------------------


def test_controller_prefix_path_param_and_request_fields(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Controllers/UsersController.cs",
        """namespace App.Controllers;

[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    [HttpGet("{id:int}")]
    public ActionResult<User> Get(int id) => Ok();

    [HttpPost]
    public IActionResult Create([FromBody] CreateUser body) => Ok();
}
""",
    )
    write(
        tmp_path,
        "Models/CreateUser.cs",
        """namespace App.Models;
public class CreateUser
{
    public required string Name { get; init; }
    [Required] public string Email { get; set; }
    public int? Age { get; set; }
    public static int Counter;
    [JsonIgnore] public string Secret { get; set; }
    [JsonPropertyName("note_text")] public string Note { get; set; }
}
""",
    )
    result = run_routes(tmp_path)
    file = "Controllers/UsersController.cs"
    assert rows_of(result, file) == [
        ["POST", "/api/users", "UsersController.Create", file, "CreateUser"],
        ["GET", "/api/users/{id:int}", "UsersController.Get", file, ""],
    ]
    l3 = section(result, file).l3_md
    assert "| Name | string | yes |" in l3
    assert "| Email | string | yes |" in l3
    assert "| Age | int? | no |" in l3
    assert "| note_text | string | no |" in l3
    assert "Counter" not in l3 and "Secret" not in l3
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert row(result).framework == "ASP.NET Core"


def test_dotnet_dynamic_path_partial(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "ItemsController.cs",
        """public class ItemsController : ControllerBase
{
    [HttpGet(Routes.Items)]
    public IActionResult A() => Ok();

    [HttpGet($"{Routes.Base}/x")]
    public IActionResult B() => Ok();

    [HttpGet("ok")]
    public IActionResult C() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/ok")]
    assert row(result).status == "partial"
    assert row(result).detail == "ItemsController.cs:3; ItemsController.cs:6"


def test_class_route_constant_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "AController.cs",
        """[Route(ApiRoutes.Base + "/a")]
public class AController : ControllerBase
{
    [HttpGet] public IActionResult Get() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == []
    assert row(result).detail == "AController.cs:1"


def test_typical_aspnet_app_reaches_complete(tmp_path):
    write(
        tmp_path,
        "src/Api/Api.csproj",
        WEB.replace(
            "</Project>",
            '  <ItemGroup>\n    <PackageReference Include="Swashbuckle.AspNetCore" Version="6.5.0" />\n    <PackageReference Include="Asp.Versioning.Mvc" Version="8.0.0" />\n  </ItemGroup>\n</Project>',
        ),
    )
    write(
        tmp_path,
        "src/Api/Program.cs",
        """var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddHealthChecks();
builder.Services.AddAuthentication().AddJwtBearer();
var app = builder.Build();
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}
app.UseHttpsRedirection();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
app.MapHealthChecks("/healthz");
app.Run();
""",
    )
    write(
        tmp_path,
        "src/Api/Controllers/OrdersController.cs",
        """using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Api.Controllers;

[ApiController]
[ApiVersion("1.0")]
[Authorize(Roles = "admin,sales")]
[Route("api/v{version:apiVersion}/[controller]")]
[Produces("application/json")]
public class OrdersController(IOrderService orders, ILogger<OrdersController> log) : ControllerBase
{
    /// <summary>List orders.</summary>
    [HttpGet]
    [ProducesResponseType(typeof(IEnumerable<OrderDto>), StatusCodes.Status200OK)]
    [SwaggerOperation(Summary = "List")]
    public async Task<ActionResult<IEnumerable<OrderDto>>> List([FromQuery] int page = 1, CancellationToken ct = default)
    {
        return Ok(await orders.ListAsync(page, ct));
    }

    [HttpGet("{id:guid}", Name = "GetOrder")]
    [AllowAnonymous]
    public async Task<ActionResult<OrderDto>> Get([FromRoute] Guid id) => Ok();

    [HttpPost]
    [ValidateAntiForgeryToken]
    [ProducesResponseType(StatusCodes.Status201Created)]
    public async Task<IActionResult> Create([FromBody] CreateOrder request)
    {
        return CreatedAtRoute("GetOrder", new { id = Guid.NewGuid() }, request);
    }

    [HttpPut("{id:guid}")]
    public IActionResult Update(Guid id, [FromBody] CreateOrder request) => NoContent();

    [HttpDelete("{id:guid}")]
    [Authorize(Policy = "AdminOnly")]
    public IActionResult Delete(Guid id) => NoContent();

    [NonAction]
    public string Helper() => "";

    private string Format(OrderDto dto) => "";
    protected IActionResult Fail() => BadRequest();
}

public record CreateOrder(string Sku, int Quantity = 1);
""",
    )
    write(
        tmp_path,
        "src/Api/Controllers/AccountController.cs",
        """namespace Api.Controllers;

[ApiController]
[Route("[controller]/[action]")]
public class AccountController : ControllerBase
{
    [HttpPost]
    public IActionResult Login([FromBody] LoginRequest r) => Ok();

    [HttpGet]
    [Authorize]
    public IActionResult Me() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert (row(result, "src/Api").status, row(result, "src/Api").detail) == (
        "complete",
        "",
    )
    assert paths(result) == sorted(
        [
            ("GET", "/api/v{version:apiVersion}/orders"),
            ("GET", "/api/v{version:apiVersion}/orders/{id:guid}"),
            ("POST", "/api/v{version:apiVersion}/orders"),
            ("PUT", "/api/v{version:apiVersion}/orders/{id:guid}"),
            ("DELETE", "/api/v{version:apiVersion}/orders/{id:guid}"),
            ("POST", "/account/Login"),
            ("GET", "/account/Me"),
            ("ANY", "/healthz"),
        ]
    )
    fields = section(result, "src/Api/Controllers/OrdersController.cs").l3_md
    assert "| Sku | string | yes |" in fields and "| Quantity | int | no |" in fields


def test_action_templates_tokens_and_verbs(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Controllers/MixController.cs",
        """[Route("api/mix")]
public class MixController : ControllerBase
{
    [HttpGet] [HttpPost]
    public IActionResult Both() => Ok();

    [HttpGet("a")] [HttpGet("b")]
    public IActionResult TwoPaths() => Ok();

    [Route("r")]
    public IActionResult OnlyRoute() => Ok();

    [HttpDelete, Route("rd/{id}")]
    public IActionResult RouteAndVerb(int id) => Ok();

    [HttpGet("/absolute")]
    public IActionResult Absolute() => Ok();

    [HttpGet("~/tilde")]
    public IActionResult Tilde() => Ok();

    [HttpGet("[action]/{id}")]
    public IActionResult Token(int id) => Ok();

    [ActionName("renamed")]
    [HttpGet("[action]")]
    public IActionResult Orig() => Ok();

    [AcceptVerbs("GET", "HEAD", Route = "av")]
    public IActionResult Verbs() => Ok();

    [HttpHead("h")]
    public IActionResult H() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == sorted(
        [
            ("GET", "/api/mix"),
            ("POST", "/api/mix"),
            ("GET", "/api/mix/a"),
            ("GET", "/api/mix/b"),
            ("ANY", "/api/mix/r"),
            ("DELETE", "/api/mix/rd/{id}"),
            ("GET", "/absolute"),
            ("GET", "/tilde"),
            ("GET", "/api/mix/Token/{id}"),
            ("GET", "/api/mix/renamed"),
            ("GET", "/api/mix/av"),
            ("HEAD", "/api/mix/av"),
            ("HEAD", "/api/mix/h"),
        ]
    )


def test_controller_token_is_lower_cased_and_unknown_tokens_are_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "UserProfilesController.cs",
        """[Route("api/[controller]")]
public class UserProfilesController : ControllerBase
{
    [HttpGet("[[literal]]")]
    public IActionResult A() => Ok();

    [HttpGet("[custom]")]
    public IActionResult B() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/api/userprofiles/[literal]")]
    assert row(result).detail == "UserProfilesController.cs:7"


def test_area_token_and_area_placeholder(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Areas/Admin/DashController.cs",
        """[Area("Admin")]
[Route("[area]/[controller]")]
public class DashController : Controller
{
    [HttpGet("x")]
    public IActionResult X() => View();
}
""",
    )
    write(
        tmp_path,
        "Areas/Shop/CartController.cs",
        """[Area("Shop")]
[Route("{area}/cart")]
public class CartController : Controller
{
    [HttpGet("y")]
    public IActionResult Y() => View();
}
""",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/Admin/dash/x") in paths(result)
    assert row(result).status == "partial"
    assert row(result).detail == "Areas/Shop/CartController.cs:5"


def test_no_class_route_attribute_routes_and_conventional_actions(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "HomeController.cs",
        """public class HomeController : Controller
{
    [HttpGet("health")]
    public IActionResult Health() => Ok();

    public IActionResult Index() => View();

    [HttpPost]
    public IActionResult Submit() => View();
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/health")]
    assert row(result).status == "partial"
    assert row(result).detail == "HomeController.cs:6; HomeController.cs:8"


def test_unattributed_public_action_with_class_route_is_any(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "PingController.cs",
        """[Route("ping")]
public class PingController : ControllerBase
{
    public IActionResult Get() => Ok();
    public override void OnActionExecuting(ActionExecutingContext c) {}
    public void Dispose() {}
    public static string Util() => "";
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("ANY", "/ping")]
    assert row(result).status == "complete"


def test_conventional_route_mapping_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}");
app.Run();
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "Program.cs:2"


def test_inherited_base_controller_actions_are_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Base.cs",
        """public abstract class CrudController<T> : ControllerBase
{
    [HttpGet("{id}")]
    public virtual IActionResult Get(int id) => Ok();
}
""",
    )
    write(
        tmp_path,
        "WidgetsController.cs",
        """[Route("widgets")]
public class WidgetsController : BaseCrud
{
    [HttpPost] public IActionResult Add() => Ok();
}
public class BaseCrud : CrudController<Widget> {}
""",
    )
    result = run_routes(tmp_path)
    assert ("POST", "/widgets") in paths(result)
    assert row(result).status == "partial"
    assert "Base.cs:3" in row(result).detail


def test_base_controller_class_route_is_inherited(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "ApiControllerBase.cs",
        """[ApiController]
[Route("api/[controller]")]
public abstract class ApiControllerBase : ControllerBase
{
    protected ISender Mediator => null;
}
""",
    )
    write(
        tmp_path,
        "TodoItemsController.cs",
        """[Authorize]
public class TodoItemsController : ApiControllerBase
{
    [HttpGet] public async Task<IActionResult> Get() => Ok();
    [HttpPut("{id}")] public async Task<IActionResult> Put(int id) => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [
        ("GET", "/api/todoitems"),
        ("PUT", "/api/todoitems/{id}"),
    ]


def test_base_with_route_and_derived_route_is_ambiguous(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "B.cs",
        '[Route("api/b")] public abstract class BBase : ControllerBase {}\n',
    )
    write(
        tmp_path,
        "DController.cs",
        '[Route("d")] public class DController : BBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "DController.cs:1" in row(result).detail


def test_unknown_external_base_class_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "ThingsController.cs",
        """[Route("things")]
public class ThingsController : ODataController
{
    [HttpGet] public IActionResult G() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/things")]
    assert row(result).status == "partial"
    assert row(result).detail == "ThingsController.cs:2"


def test_abstract_class_with_handlers_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "GenBase.cs",
        """[ApiController]
public abstract class UsersControllerBase : ControllerBase
{
    [HttpGet, Route("users")]
    public abstract Task<IActionResult> Get();
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "GenBase.cs:4"


def test_controller_that_yields_nothing_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "EmptyController.cs",
        """public class EmptyController : ControllerBase
{
    private int Helper() => 1;
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "EmptyController.cs:1"


def test_non_controller_and_attribute_composition(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Attrs.cs",
        """public class ApiGetAttribute : HttpGetAttribute
{
    public ApiGetAttribute(string t) : base("v1/" + t) {}
}
""",
    )
    write(
        tmp_path,
        "TController.cs",
        """[NonController]
public class HiddenController : ControllerBase
{
    [HttpGet("hidden")] public IActionResult A() => Ok();
}
public class TController : ControllerBase
{
    [ApiGet("x")] public IActionResult B() => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == []
    assert row(result).status == "partial"
    assert "TController.cs:8" in row(result).detail


def test_partial_controller_parts_are_merged(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Orders.Routes.cs",
        '[Route("orders")]\npublic partial class OrdersController : ControllerBase {}\n',
    )
    write(
        tmp_path,
        "Orders.Actions.cs",
        'public partial class OrdersController\n{\n    [HttpGet("{id}")] public IActionResult Get(int id) => Ok();\n}\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [("GET", "/orders/{id}")]


def test_sites_for_global_route_conventions_and_path_base(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Startup.cs",
        """public class Startup
{
    public void ConfigureServices(IServiceCollection s)
    {
        s.AddControllers(o => o.Conventions.Add(new RoutePrefixConvention("api")));
    }
    public void Configure(IApplicationBuilder app)
    {
        app.UsePathBase("/svc");
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "Startup.cs:5; Startup.cs:9"


def test_openapi_generator_in_build_is_a_site(tmp_path):
    write(
        tmp_path,
        "Api.csproj",
        WEB.replace(
            "</Project>",
            '  <ItemGroup>\n    <PackageReference Include="NSwag.MSBuild" Version="14.0.0" />\n  </ItemGroup>\n</Project>',
        ),
    )
    write(
        tmp_path,
        "UsersController.cs",
        '[Route("u")] public class UsersController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "Api.csproj:6"


def test_test_projects_are_not_product_routes(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "tests/Api.Tests/Api.Tests.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n<ItemGroup><PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.0.0" /></ItemGroup>\n</Project>\n',
    )
    write(
        tmp_path,
        "tests/Api.Tests/FakeController.cs",
        '[Route("fake")] public class FakeController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    write(
        tmp_path,
        "src/Api.Tests/Api.Tests.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n<ItemGroup><PackageReference Include="xunit" Version="2.6.0" /></ItemGroup>\n</Project>\n',
    )
    write(
        tmp_path,
        "src/Api.Tests/FooTests.cs",
        'public class FooTests { void T(WebApplication app) { app.MapGet("/t", () => 1); } }\n',
    )
    write(
        tmp_path,
        "Real.cs",
        'public class RealController : ControllerBase { [HttpGet("real")] public IActionResult G() => Ok(); }\n',
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/real")]
    assert row(result).status == "complete"


def test_syntax_error_in_a_controller_file_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "BadController.cs",
        'public class BadController : ControllerBase\n{\n    [HttpGet("x")] public IActionResult G( { }\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "BadController.cs:" in row(result).detail


def test_web_project_with_no_routes_is_a_site_at_the_sdk_line(tmp_path):
    web(tmp_path)
    write(tmp_path, "Util.cs", "public class Util {}\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "Api.csproj:1"


def test_package_only_project_and_framework_reference_are_labelled(tmp_path):
    write(
        tmp_path,
        "Lib/Lib.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n  <ItemGroup>\n    <PackageReference Include="Microsoft.AspNetCore.Mvc.Core" Version="2.2.5" />\n  </ItemGroup>\n</Project>\n',
    )
    write(
        tmp_path,
        "Shared/Shared.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n  <ItemGroup>\n    <FrameworkReference Include="Microsoft.AspNetCore.App" />\n  </ItemGroup>\n</Project>\n',
    )
    write(tmp_path, "Lib/A.cs", "public class A {}\n")
    write(tmp_path, "Shared/B.cs", "public class B {}\n")
    result = run_routes(tmp_path)
    assert row(result, "Lib").detail == "Lib/Lib.csproj:3"
    assert row(result, "Shared").detail == "Shared/Shared.csproj:3"


def test_integration_test_project_is_not_a_web_module(tmp_path):
    write(
        tmp_path,
        "tests/Api.IntegrationTests/Api.IntegrationTests.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n  <ItemGroup>\n    <PackageReference Include="Microsoft.AspNetCore.Mvc.Testing" Version="8.0.0" />\n  </ItemGroup>\n</Project>\n',
    )
    write(
        tmp_path,
        "tests/Api.IntegrationTests/A.cs",
        "public class ApiTests { }\n",
    )
    result = run_routes(tmp_path)
    assert row(result, "tests/Api.IntegrationTests").status == "complete"


def test_routes_are_deterministic(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "AController.cs",
        '[Route("a")] public class AController : ControllerBase { [HttpGet("{x}")] public IActionResult G(int x) => Ok(); }\n',
    )
    first = run_routes(tmp_path)
    second = run_routes(tmp_path)
    assert [(s.id, s.l2_md, s.l3_md) for s in first.sections] == [
        (s.id, s.l2_md, s.l3_md) for s in second.sections
    ]
    assert first.coverage == second.coverage


def test_request_type_outside_repo_and_base_class(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "PController.cs",
        """[Route("p")]
public class PController : ControllerBase
{
    [HttpPost("a")] public IActionResult A([FromBody] ExternalDto d) => Ok();
    [HttpPost("b")] public IActionResult B([FromBody] Derived d) => Ok();
    [HttpPost("c")] public IActionResult C([FromBody] List<Item> d) => Ok();
}
public class Derived : BaseDto { public string Own { get; set; } }
public class Item { public string Id { get; set; } }
""",
    )
    result = run_routes(tmp_path)
    l3 = section(result, "PController.cs").l3_md
    assert "ExternalDto: request type declared outside the repo" in l3
    assert "Derived: request type declared outside the repo" in l3
    assert "| Id | string | no |" in l3


def test_positional_record_request_fields(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "RController.cs",
        """[Route("r")]
public class RController : ControllerBase
{
    [HttpPost] public IActionResult A([FromBody] Req d) => Ok();
}
public record Req(string Name, [property: Required] string Code, int Count = 3);
""",
    )
    l3 = section(run_routes(tmp_path), "RController.cs").l3_md
    assert "| Name | string | yes |" in l3
    assert "| Code | string | yes |" in l3
    assert "| Count | int | no |" in l3


def test_other_language_route_files_do_not_read_cs_types(tmp_path):
    # a TS route whose request type has the same name as a C# class
    write(tmp_path, "package.json", '{"dependencies":{"@nestjs/core":"10"}}')
    write(
        tmp_path,
        "a.controller.ts",
        "@Controller('a') class A { @Post() c(@Body() b: Dto) {} }\n",
    )
    write(tmp_path, "Dto.cs", "public class Dto { public string Leak { get; set; } }\n")
    result = run_routes(tmp_path)
    assert "Leak" not in "".join(s.l3_md for s in result.sections)


# --- minimal APIs -----------------------------------------------------------


def test_minimal_api_groups_chains_and_methods(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.MapGet("/", () => "hello");
app.MapGet("/ping", Handlers.Ping);

var api = app.MapGroup("/api").RequireAuthorization().WithTags("api");
api.MapGet("/items/{id:int}", (int id) => Results.Ok());
api.MapPost("/items", ([FromBody] CreateItem body) => Results.Created());

var v1 = api.MapGroup("v1");
v1.MapDelete("/items/{id}", async (int id, ItemDb db) => await db.Remove(id));
v1.MapPut("/items/{id}", UpdateItem);

app.MapGroup("/admin").MapPatch("/x", () => 1).WithName("x");
app.MapMethods("/multi", new[] { "GET", "POST" }, () => 1);
app.MapMethods("/coll", ["PUT"], () => 1);
app.Run();

public record CreateItem(string Name, string? Note);
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == sorted(
        [
            ("GET", "/"),
            ("GET", "/ping"),
            ("GET", "/api/items/{id:int}"),
            ("POST", "/api/items"),
            ("DELETE", "/api/v1/items/{id}"),
            ("PUT", "/api/v1/items/{id}"),
            ("PATCH", "/admin/x"),
            ("GET", "/multi"),
            ("POST", "/multi"),
            ("PUT", "/coll"),
        ]
    )
    rows = {(r[0], r[1]): r for r in rows_of(run_routes(tmp_path), "Program.cs")}
    assert rows[("GET", "/ping")][2] == "Handlers.Ping"
    assert rows[("GET", "/")][2] == "(inline)"
    assert rows[("POST", "/api/items")][4] == "CreateItem"
    assert "| Name | string | yes |" in section(result, "Program.cs").l3_md
    assert (
        "| Note | string? | yes |" in section(result, "Program.cs").l3_md
    )  # positional, no default


def test_minimal_api_dynamic_paths_are_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
app.MapGet(Routes.Home, () => 1);
var g = app.MapGroup(prefix);
g.MapGet("/a", () => 1);
app.MapGet($"/{ver}/b", () => 1);
app.MapMethods("/m", verbs, () => 1);
app.MapGet("/ok", () => 1);
app.Run();
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/ok")]
    assert row(result).status == "partial"
    assert (
        row(result).detail
        == "Program.cs:2; Program.cs:3; Program.cs:4; Program.cs:5; Program.cs:6"
    )


def test_minimal_api_unfollowed_constructs_are_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
app.MapFallback(() => "x");
app.MapFallbackToFile("index.html");
app.Map("/branch", b => b.Run(ctx => ctx.Response.WriteAsync("x")));
app.MapHub<ChatHub>("/chat");
app.MapGrpcService<Greeter>();
app.MapIdentityApi<AppUser>();
app.MapCarter();
app.MapControllers();
app.MapRazorPages();
app.MapOpenApi();
""",
    )
    result = run_routes(tmp_path)
    assert row(result).detail == "; ".join(f"Program.cs:{n}" for n in range(2, 9))


def test_extension_method_endpoint_groups_are_followed(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
app.MapGroup("/api").MapUserEndpoints();
app.MapTodoEndpoints();
UserEndpoints.MapExtra(app);
app.Run();
""",
    )
    write(
        tmp_path,
        "Endpoints/UserEndpoints.cs",
        """public static class UserEndpoints
{
    public static RouteGroupBuilder MapUserEndpoints(this RouteGroupBuilder routes)
    {
        var g = routes.MapGroup("/users").WithTags("Users");
        g.MapGet("/", () => 1);
        g.MapGet("/{id}", (int id) => 1);
        return g;
    }

    public static void MapTodoEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/todos", ([FromBody] TodoDto t) => 1);
    }

    public static void MapExtra(IEndpointRouteBuilder app) => app.MapGet("/extra", () => 1);
}
public class TodoDto { public string Title { get; set; } }
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == sorted(
        [
            ("GET", "/api/users"),
            ("GET", "/api/users/{id}"),
            ("POST", "/todos"),
            ("GET", "/extra"),
        ]
    )
    assert (
        "| Title | string | no |" in section(result, "Endpoints/UserEndpoints.cs").l3_md
    )


def test_uncalled_endpoint_helper_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        "var app = WebApplication.CreateBuilder(args).Build();\napp.Run();\n",
    )
    write(
        tmp_path,
        "Ext.cs",
        """public static class Ext
{
    public static void MapOrphans(this IEndpointRouteBuilder app)
    {
        app.MapGet("/o", () => 1);
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == []
    assert row(result).detail == "Ext.cs:5"


def test_helper_value_used_as_group_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
var g = app.MapThings();
g.MapGet("/more", () => 1);
""",
    )
    write(
        tmp_path,
        "Things.cs",
        """public static class Things
{
    public static RouteGroupBuilder MapThings(this IEndpointRouteBuilder app)
    {
        return app.MapGroup("/things");
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "Program.cs:2" in row(result).detail


def test_startup_use_endpoints_lambda(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Startup.cs",
        """public class Startup
{
    public void Configure(IApplicationBuilder app, IWebHostEnvironment env)
    {
        app.UseRouting();
        app.UseEndpoints(endpoints =>
        {
            endpoints.MapControllers();
            endpoints.MapGet("/status", async ctx => await ctx.Response.WriteAsync("ok"));
            endpoints.MapGroup("/v2").MapPost("/jobs", Jobs.Create);
        });
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [("GET", "/status"), ("POST", "/v2/jobs")]


def test_map_call_outside_any_scanned_unit_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Fields.cs",
        """public class Fields
{
    private static readonly Action<WebApplication> Reg = a => a.MapGet("/field", () => 1);
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == []
    assert row(result).detail == "Fields.cs:3"


def test_razor_pages_and_cshtml_are_not_routes(tmp_path):
    web(tmp_path)
    write(tmp_path, "Pages/Index.cshtml", '@page "/home"\n<h1>x</h1>\n')
    write(
        tmp_path,
        "Pages/Index.cshtml.cs",
        "public class IndexModel : PageModel { public void OnGet() {} }\n",
    )
    write(
        tmp_path,
        "Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\napp.MapRazorPages();\napp.MapGet("/api/x", () => 1);\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [("GET", "/api/x")]


def test_use_path_base_regex_ignores_comments(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\n// app.UsePathBase("/x");\napp.MapGet("/a", () => 1);\n',
    )
    assert row(run_routes(tmp_path)).status == "complete"


def test_two_scopes_one_repo(tmp_path):
    web(tmp_path, "src/A")
    web(tmp_path, "src/B")
    write(
        tmp_path,
        "src/A/Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\napp.MapGet("/a", () => 1);\n',
    )
    write(
        tmp_path,
        "src/B/Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\napp.MapGet("/b", () => 1);\n',
    )
    result = run_routes(tmp_path)
    assert {r.scope: r.status for r in result.coverage} == {
        "src/A": "complete",
        "src/B": "complete",
    }
    assert paths(result) == [("GET", "/a"), ("GET", "/b")]


def test_conditional_compilation_alternatives_are_sites_and_members_count(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "AController.cs",
        """#nullable enable
[Route("a")]
public class AController : ControllerBase
{
#if DEBUG
    [HttpGet("dbg")]
#else
    [HttpGet("rel")]
#endif
    public IActionResult G() => Ok();

#if NET8_0_OR_GREATER
    [HttpPost("p")]
    public IActionResult P() => Ok();
#endif
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [
        ("GET", "/a/dbg"),
        ("GET", "/a/rel"),
        ("POST", "/a/p"),
    ]
    assert row(result).detail == "AController.cs:6; AController.cs:8"


def test_base_controller_without_actions_is_not_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "BaseApiController.cs",
        """[ApiController]
[Route("api/[controller]")]
public class BaseApiController : ControllerBase { }
""",
    )
    write(
        tmp_path,
        "ProductsController.cs",
        """public class ProductsController(IRepo repo) : BaseApiController
{
    [HttpGet] public IActionResult All() => Ok();
    [HttpGet("{id:int}")] public IActionResult One(int id) => Ok();
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [
        ("GET", "/api/products"),
        ("GET", "/api/products/{id:int}"),
    ]


def test_builder_stored_in_a_field_or_loop_variable_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "UserModule.cs",
        """public class UserModule
{
    private readonly RouteGroupBuilder _group;
    public UserModule(IEndpointRouteBuilder app) { _group = app.MapGroup("/users"); }
    public void Register() { _group.MapGet("/", () => 1); }
}
""",
    )
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
foreach (var g in Groups(app)) g.MapGet("/a", () => 1);
var other = Create(app);
other.MapGet("/b", () => 1);
app.MapGet("/ok", () => 1);
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/ok")]
    assert row(result).detail == (
        "Program.cs:2; Program.cs:4; UserModule.cs:4; UserModule.cs:5"
    )


def test_lambda_builder_from_unfollowed_code_is_a_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
app.WithGroup("/x", g => g.MapGet("/a", () => 1));
app.UseEndpoints(e => e.MapGet("/b", () => 1));
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == [("GET", "/b")]
    assert row(result).detail == "Program.cs:2"


def test_versioned_api_helper_with_health_checks(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapDefaultEndpoints();
app.MapCatalogApi();
app.Run();
""",
    )
    write(
        tmp_path,
        "Apis/CatalogApi.cs",
        """public static class CatalogApi
{
    public static IEndpointRouteBuilder MapCatalogApi(this IEndpointRouteBuilder app)
    {
        var vApi = app.NewVersionedApi("Catalog");
        var api = vApi.MapGroup("api/catalog").HasApiVersion(1, 0);
        api.MapGet("/items", GetAllItems);
        api.MapPost("/items", CreateItem);
        api.MapDelete("/items/{id:int}", DeleteItemById).RequireAuthorization();
        return app;
    }
}
public static class Extensions
{
    public static WebApplication MapDefaultEndpoints(this WebApplication app)
    {
        if (app.Environment.IsDevelopment())
        {
            app.MapHealthChecks("/health");
        }
        return app;
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [
        ("ANY", "/health"),
        ("DELETE", "/api/catalog/items/{id:int}"),
        ("GET", "/api/catalog/items"),
        ("POST", "/api/catalog/items"),
    ]


def test_generated_server_stub_and_interface_handlers_are_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "IUsers.cs",
        'public interface IUsersApi { [HttpGet("u")] Task<IActionResult> Get(); }\n',
    )
    write(
        tmp_path,
        "Gen.cs",
        """// <auto-generated/>
[Microsoft.AspNetCore.Mvc.ApiController]
public abstract class PetControllerBase : Microsoft.AspNetCore.Mvc.ControllerBase
{
    [Microsoft.AspNetCore.Mvc.HttpGet, Microsoft.AspNetCore.Mvc.Route("pets/{id}")]
    public abstract System.Threading.Tasks.Task<Microsoft.AspNetCore.Mvc.IActionResult> Get(long id);
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).detail == "Gen.cs:5; IUsers.cs:1"


def test_qualified_verbatim_raw_and_named_arguments(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "QController.cs",
        '''[Microsoft.AspNetCore.Mvc.Route(@"v1/q")]
public class QController : Microsoft.AspNetCore.Mvc.ControllerBase
{
    [Microsoft.AspNetCore.Mvc.HttpGetAttribute("{id}")]
    public IActionResult Get(int id) => null;
    [HttpGet(template: "named")]
    public IActionResult N() => null;
    [Route(template: "rt"), HttpPost]
    public IActionResult R() => null;
    [HttpGet("""raw/{x}""")]
    public IActionResult Raw(int x) => null;
    [HttpGet(@"with""quote")]
    public IActionResult Q() => null;
}
''',
    )
    result = run_routes(tmp_path)
    assert paths(result) == sorted(
        [
            ("GET", "/v1/q/{id}"),
            ("GET", "/v1/q/named"),
            ("POST", "/v1/q/rt"),
            ("GET", "/v1/q/raw/{x}"),
        ]
    )
    assert row(result).detail == "QController.cs:12"


def test_bom_and_crlf_sources_parse_cleanly(tmp_path):
    web(tmp_path)
    (tmp_path / "AController.cs").write_bytes(
        b'\xef\xbb\xbfusing System;\r\n[Route("a")]\r\npublic class AController : ControllerBase\r\n{\r\n'
        b"  [HttpGet] public IActionResult G() => Ok();\r\n}\r\n"
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete"
    assert paths(result) == [("GET", "/a")]


def test_pages_only_web_app_is_not_a_site_but_an_empty_one_is(tmp_path):
    web(tmp_path)
    write(tmp_path, "Pages/Index.cshtml", "@page\n<h1>x</h1>\n")
    write(
        tmp_path,
        "Program.cs",
        "var app = WebApplication.CreateBuilder(args).Build();\napp.MapRazorPages();\n",
    )
    assert row(run_routes(tmp_path)).status == "complete"
    (tmp_path / "Pages/Index.cshtml").unlink()
    assert row(run_routes(tmp_path)).detail == "Api.csproj:1"


def test_unattributed_actions_in_a_controller_with_a_repo_base_are_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "BaseController.cs",
        "public abstract class AppBase : Controller { }\n",
    )
    write(
        tmp_path,
        "HomeController.cs",
        "public class HomeController : AppBase\n{\n    public IActionResult Index() => View();\n}\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "HomeController.cs:3"


def test_async_suffix_is_dropped_from_the_action_token(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "AccountController.cs",
        """[Route("[controller]/[action]")]
public class AccountController : ControllerBase
{
    [HttpPost] public Task<IActionResult> LoginAsync() => null;
    [HttpPost] public Task<IActionResult> Async() => null;
}
""",
    )
    assert paths(run_routes(tmp_path)) == [
        ("POST", "/account/Async"),
        ("POST", "/account/Login"),
    ]


def test_api_version_conventions_on_minimal_endpoints_are_not_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var app = WebApplication.CreateBuilder(args).Build();
var set = app.NewApiVersionSet().Build();
app.MapGet("/v", () => 1).WithApiVersionSet(set).MapToApiVersion(1.0);
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [("GET", "/v")]


def test_web_sdk_and_framework_reference_make_an_aspnet_scope(tmp_path):
    from strata_kb.codeingest.extractors import _scopes

    write(tmp_path, "a/A.csproj", WEB)
    write(
        tmp_path,
        "b/B.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n<ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App" /></ItemGroup>\n</Project>\n',
    )
    write(tmp_path, "c/C.csproj", '<Project Sdk="Microsoft.NET.Sdk"></Project>\n')
    scopes = _scopes.find_scopes(tmp_path, tmp_path / ".kb")
    assert {s.path: s.frameworks for s in scopes} == {
        "a": ("ASP.NET Core",),
        "b": ("ASP.NET Core",),
        "c": (),
    }


def test_route_prefix_attribute_is_a_site_but_swagger_route_prefix_is_not(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\napp.UseSwaggerUI(c => c.RoutePrefix = "docs");\napp.MapGet("/a", () => 1);\n',
    )
    assert row(run_routes(tmp_path)).status == "complete"
    write(
        tmp_path,
        "LegacyController.cs",
        '[RoutePrefix("old")] public class LegacyController : ApiController { [HttpGet] public int Get() => 1; }\n',
    )
    assert "LegacyController.cs:1" in row(run_routes(tmp_path)).detail


def test_libraries_that_only_touch_http_or_auth_are_not_web_modules(tmp_path):
    for name, package in (
        ("Auth", "Microsoft.AspNetCore.Authorization"),
        ("Blazor", "Microsoft.AspNetCore.Components.WebAssembly"),
        ("Http", "Microsoft.AspNetCore.Http.Abstractions"),
    ):
        write(
            tmp_path,
            f"{name}/{name}.csproj",
            f'<Project Sdk="Microsoft.NET.Sdk">\n<ItemGroup><PackageReference Include="{package}" Version="8.0.0" /></ItemGroup>\n</Project>\n',
        )
        write(
            tmp_path,
            f"{name}/A.cs",
            "using Microsoft.AspNetCore.Http;\npublic class A {}\n",
        )
    result = run_routes(tmp_path)
    assert {r.scope: r.status for r in result.coverage} == {
        "Auth": "complete",
        "Blazor": "complete",
        "Http": "complete",
    }


def test_library_that_uses_mvc_types_but_declares_no_route_is_a_site(tmp_path):
    write(
        tmp_path,
        "Lib/Lib.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n<ItemGroup><PackageReference Include="Microsoft.AspNetCore.Authorization" Version="8.0.0" /></ItemGroup>\n</Project>\n',
    )
    write(
        tmp_path,
        "Lib/Handlers.cs",
        "using Microsoft.AspNetCore.Mvc;\npublic class UsersHandler { public IActionResult Get() => null; }\n",
    )
    assert row(run_routes(tmp_path), "Lib").detail == "Lib/Handlers.cs:1"


# --- fix round 1 ------------------------------------------------------------


def test_helper_reached_only_from_a_file_with_no_route_words_is_followed(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """using Api;
var builder = WebApplication.CreateBuilder(args);
var app = builder.ConfigureServices().ConfigurePipeline();
app.Run();
""",
    )
    write(
        tmp_path,
        "HostingExtensions.cs",
        """namespace Api;
internal static class HostingExtensions
{
    public static WebApplication ConfigureServices(this WebApplicationBuilder builder)
    {
        builder.Services.AddControllers();
        return builder.Build();
    }
    public static WebApplication ConfigurePipeline(this WebApplication app)
    {
        app.UseAuthorization();
        app.MapControllers();
        app.MapGet("/status", () => "ok");
        app.RegisterTodoEndpoints();
        return app;
    }
}
""",
    )
    write(
        tmp_path,
        "Endpoints/Todo.cs",
        """namespace Api.Endpoints;
public static class TodoEndpoints
{
    public static void RegisterTodoEndpoints(this IEndpointRouteBuilder routes)
    {
        var g = routes.MapGroup("/todos");
        g.MapGet("/", () => "x");
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete", row(result).detail
    assert paths(result) == [("GET", "/status"), ("GET", "/todos")]


def test_uncalled_helper_makes_its_map_calls_sites(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        "var app = WebApplication.CreateBuilder(args).Build();\n",
    )
    write(
        tmp_path,
        "Ext.cs",
        """public static class Ext
{
    public static void MapOrphans(this IEndpointRouteBuilder app)
    {
        app.MapGet("/o", () => 1);
        app.MapPost("/p", () => 1);
    }
    public static void MapQuiet(this IEndpointRouteBuilder app) { }
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == []
    assert row(result).detail == "Ext.cs:5; Ext.cs:6"


def test_helper_called_from_another_scope_is_not_a_site_in_its_own(tmp_path):
    write(tmp_path, "Shared/Shared.csproj", WEB)
    write(
        tmp_path,
        "Shared/Ext.cs",
        'public static class Ext { public static void MapShared(this IEndpointRouteBuilder a) { a.MapGet("/s", () => 1); } }\n',
    )
    write(tmp_path, "Host/Host.csproj", WEB)
    write(
        tmp_path,
        "Host/Program.cs",
        "var app = WebApplication.CreateBuilder(args).Build();\napp.MapShared();\n",
    )
    result = run_routes(tmp_path)
    assert row(result, "Shared").status == "complete"
    assert row(result, "Host").status == "complete"
    assert paths(result) == [("GET", "/s")]


def test_product_folders_and_files_named_tests_are_kept(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Features/LabTests/LabTestsController.cs",
        '[Route("labtests")] public class LabTestsController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    write(
        tmp_path,
        "Domain/LabTest.cs",
        "public class LabTest { public const int Max = 3; }\n",
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/labtests")]
    assert ("LabTest", "class") in names_of(run_symbols(tmp_path))


@pytest.mark.parametrize(
    "marker",
    [
        '<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.0.0" />',
        '<PackageReference Include="xunit" Version="2.6.0" />',
        '<PackageReference Include="NUnit" Version="4.0.0" />',
        '<PackageReference Include="MSTest.TestFramework" Version="3.0.0" />',
        "<IsTestProject>true</IsTestProject>",
    ],
)
def test_files_in_a_test_project_are_skipped_by_routes_and_symbols(tmp_path, marker):
    web(tmp_path, "src/Api")
    write(
        tmp_path,
        "src/Api/Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\napp.MapGet("/real", () => 1);\n',
    )
    write(
        tmp_path,
        "src/Api.Specs/Api.Specs.csproj",
        f'<Project Sdk="Microsoft.NET.Sdk.Web">\n<ItemGroup>{marker}</ItemGroup>\n</Project>\n',
    )
    write(
        tmp_path,
        "src/Api.Specs/Fake.cs",
        'public class FakeController : ControllerBase { [HttpGet("fake")] public IActionResult G() => Ok(); }\npublic class Fixture { }\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/real")]
    got = names_of(run_symbols(tmp_path))
    assert ("Fixture", "class") not in got and ("FakeController", "class") not in got


def test_symbols_test_rule_does_not_leak_to_other_languages(tmp_path):
    write(tmp_path, "web/package.json", '{"name":"w"}')
    write(tmp_path, "web/src/ABTests/flags.ts", "export const FLAG = 1;\n")
    result = run_symbols(tmp_path)
    assert ("FLAG", "const") in names_of(result)


def test_builder_parameters_of_ordinary_methods_are_not_the_app(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        """var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapGet("/health-x", () => "ok");
app.MapGroup("/api/v1").AddUsers();
app.MapGroup("/api/v2").AddMaybe();
Local(app.MapGroup("/api/v3"));
app.Run();
void Local(RouteGroupBuilder g) { g.MapGet("/local", () => 1); }
""",
    )
    write(
        tmp_path,
        "Users.cs",
        """public static class UsersEndpoints
{
    public static TBuilder AddUsers<TBuilder>(this TBuilder builder) where TBuilder : IEndpointRouteBuilder
    {
        builder.MapGet("/users", () => "u");
        return builder;
    }
    public static void AddMaybe(this IEndpointRouteBuilder? builder)
    {
        builder!.MapGet("/maybe", () => "u");
    }
    public static void Inner(IEndpointRouteBuilder b)
    {
        void Reg(RouteGroupBuilder g) { g.MapGet("/inner", () => 1); }
        Reg(b.MapGroup("/x"));
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == sorted(
        [
            ("GET", "/health-x"),
            ("GET", "/api/v1/users"),
            ("GET", "/api/v2/maybe"),
            ("GET", "/api/v3/local"),
        ]
    )
    assert row(result).detail == "Users.cs:14"  # the nested local function


def test_method_parameter_builders_are_not_assumed_to_be_the_app(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "X.cs",
        """public class X
{
    public void Register(Foo registry) { registry.MapGet("/r", () => 1); }
    public void Real(WebApplication app) { app.MapGet("/real", () => 1); }
}
""",
    )
    result = run_routes(tmp_path)
    assert paths(result) == []
    assert row(result).detail == "X.cs:3; X.cs:4"  # `Real` is a helper nothing calls


def test_record_parameter_with_property_json_ignore_is_skipped(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "RController.cs",
        """[Route("r")]
public class RController : ControllerBase
{
    [HttpPost] public IActionResult A([FromBody] Req d) => Ok();
}
public record Req(string Name, [property: JsonIgnore] string Secret);
""",
    )
    l3 = section(run_routes(tmp_path), "RController.cs").l3_md
    assert "| Name | string | yes |" in l3 and "Secret" not in l3


@pytest.mark.parametrize(
    "base",
    [
        "EndpointWithoutRequest",
        "Endpoint<Req>",
        "Ep.Req<Dto>.Res<Out>",
        "Ep.NoReq.Res<Out>",
    ],
)
def test_fast_endpoints_base_classes_are_sites(tmp_path, base):
    web(tmp_path)
    write(
        tmp_path,
        "Ep.cs",
        f'public class Hello : {base}\n{{\n    public override void Configure() {{ Get("/hello"); }}\n}}\n',
    )
    assert row(run_routes(tmp_path)).detail == "Ep.cs:1"


def test_base_named_like_an_interface_is_a_class_when_the_repo_says_so(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "IAMController.cs",
        '[Route("iam")] public abstract class IAMController : ControllerBase { [HttpGet("base")] public IActionResult B() => Ok(); }\n',
    )
    write(
        tmp_path,
        "UsersController.cs",
        'public class UsersController : IAMController, IDisposable { [HttpGet("u")] public IActionResult G() => Ok(); public void Dispose() {} }\n',
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "IAMController.cs:1" in row(result).detail


def test_controller_token_strips_the_suffix_case_insensitively(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "XCONTROLLER.cs",
        '[Route("[controller]")] public class UsersCONTROLLER : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/users")]


def test_a_folder_named_tests_in_a_product_project_is_kept(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Features/Tests/TestsController.cs",
        '[Route("t")] public class TestsController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    write(tmp_path, "Features/Tests/Plan.cs", "public class Plan { }\n")
    assert paths(run_routes(tmp_path)) == [("GET", "/t")]
    assert ("Plan", "class") in names_of(run_symbols(tmp_path))


@pytest.mark.parametrize("props", ["Directory.Build.props", "Directory.Packages.props"])
def test_test_framework_from_directory_props_marks_a_test_project(tmp_path, props):
    web(tmp_path, "src/Api")
    write(
        tmp_path,
        "src/Api/Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\napp.MapGet("/real", () => 1);\n',
    )
    write(
        tmp_path,
        "specs/Api.Specs/Api.Specs.csproj",
        '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>\n',
    )
    write(
        tmp_path,
        f"specs/{props}",
        '<Project><ItemGroup><PackageReference Include="xunit" Version="2.6.0" /></ItemGroup></Project>\n',
    )
    write(
        tmp_path,
        "specs/Api.Specs/Fake.cs",
        'public class FakeController : ControllerBase { [HttpGet("fake")] public IActionResult G() => Ok(); }\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/real")]


def test_internals_visible_to_a_test_assembly_does_not_make_a_test_project(tmp_path):
    write(
        tmp_path,
        "Api.csproj",
        WEB.replace(
            "</Project>",
            '  <ItemGroup>\n    <InternalsVisibleTo Include="Api.xUnitTests" />\n  </ItemGroup>\n</Project>',
        ),
    )
    write(
        tmp_path,
        "UsersController.cs",
        '[Route("u")] public class UsersController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\n',
    )
    assert paths(run_routes(tmp_path)) == [("GET", "/u")]


def test_endpoint_in_a_ternary_or_call_is_not_a_fast_endpoints_base(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Program.cs",
        'var app = WebApplication.CreateBuilder(args).Build();\nvar x = flag ? a : Endpoint.Create();\nF(name: Endpoint.Id);\napp.MapGet("/a", () => 1);\n',
    )
    assert row(run_routes(tmp_path)).status == "complete"


PRODUCT_API = (
    "src/Api/Controllers/UsersController.cs",
    '[Route("api/u")] public class UsersController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\npublic class Plan { }\n',
)
FAKE_API = (
    "qa/Api.Tests/FakeController.cs",
    '[Route("fake")] public class FakeController : ControllerBase { [HttpGet] public IActionResult G() => Ok(); }\npublic class Fixture { }\n',
)


def two_projects(
    root: Path,
    props: str,
    tests_csproj: str = '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>\n',
):
    write(root, "src/Api/Api.csproj", WEB)
    write(root, "qa/Api.Tests/Api.Tests.csproj", tests_csproj)
    write(root, "Directory.Build.props", props)
    for rel, text in (PRODUCT_API, FAKE_API):
        write(root, rel, text)


XUNIT = '<PackageReference Include="xunit" Version="2.6.0" /><PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.0.0" />'


SPECS = "Condition=\"$(MSBuildProjectName.Contains('Specs'))\" "
XUNIT_SPECS = XUNIT.replace("<PackageReference ", "<PackageReference " + SPECS)


@pytest.mark.parametrize(
    ("props", "tests_csproj", "tests_skipped"),
    [
        # name-conditioned refs apply to the project whose file name matches
        (
            f"<Project><ItemGroup Condition=\"$(MSBuildProjectName.EndsWith('Tests'))\">{XUNIT}</ItemGroup></Project>",
            None,
            True,
        ),
        (
            f"<Project><ItemGroup Condition=\"$(MSBuildProjectName).StartsWith('Api.T')\">{XUNIT}</ItemGroup></Project>",
            None,
            True,
        ),
        (
            f"<Project><ItemGroup Condition=\"'$(MSBuildProjectName)' == 'Api.Tests'\">{XUNIT}</ItemGroup></Project>",
            None,
            True,
        ),
        (
            f"<Project><ItemGroup>{XUNIT_SPECS}</ItemGroup></Project>",
            None,
            False,
        ),
        # IsTestProject-conditioned refs need the csproj to say so
        (
            f"<Project><ItemGroup Condition=\"'$(IsTestProject)' == 'true'\">{XUNIT}</ItemGroup></Project>",
            None,
            False,
        ),
        (
            f"<Project><ItemGroup Condition=\"'$(IsTestProject)' == 'true'\">{XUNIT}</ItemGroup></Project>",
            '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup></Project>',
            True,
        ),
        # any other condition is not evaluated: not a test project
        (
            f"<Project><ItemGroup Condition=\"'$(TargetFramework)' == 'net8.0'\">{XUNIT}</ItemGroup></Project>",
            None,
            False,
        ),
        (
            f"<Project><ItemGroup Condition=\"Exists('x.txt')\">{XUNIT}</ItemGroup></Project>",
            None,
            False,
        ),
        # unconditional props reference: every project below is a test project
        (f"<Project><ItemGroup>{XUNIT}</ItemGroup></Project>", None, True),
    ],
)
def test_conditions_on_props_references_are_evaluated_against_the_project(
    tmp_path, props, tests_csproj, tests_skipped
):
    two_projects(
        tmp_path,
        props,
        tests_csproj or '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>\n',
    )
    got = names_of(run_symbols(tmp_path))
    if (
        props.count("Condition") == 0
        and "<PackageReference " in props
        and tests_skipped
    ):
        # unconditional: the product project is a test project too
        assert ("Plan", "class") not in got
        return
    assert ("Plan", "class") in got
    assert (("Fixture", "class") not in got) is tests_skipped
    expected = (
        [("GET", "/api/u")] if tests_skipped else [("GET", "/api/u"), ("GET", "/fake")]
    )
    assert paths(run_routes(tmp_path)) == expected


def test_only_the_nearest_directory_props_applies_unless_it_imports_the_parent(
    tmp_path,
):
    write(
        tmp_path,
        "Directory.Build.props",
        f"<Project><ItemGroup>{XUNIT}</ItemGroup></Project>",
    )
    write(tmp_path, "src/Directory.Build.props", "<Project></Project>")
    write(tmp_path, "src/Api/Api.csproj", WEB)
    write(tmp_path, PRODUCT_API[0], PRODUCT_API[1])
    assert paths(run_routes(tmp_path)) == [("GET", "/api/u")]
    write(
        tmp_path,
        "src/Directory.Build.props",
        "<Project><Import Project=\"$([MSBuild]::GetPathOfFileAbove('Directory.Build.props', '$(MSBuildThisFileDirectory)../'))\" /></Project>",
    )
    assert paths(run_routes(tmp_path)) == []


def test_fast_endpoints_base_after_a_primary_constructor_with_defaults(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Ep.cs",
        "public class Hello(IFoo? foo = null) : Endpoint<Req, Res>\n{\n}\n",
    )
    assert row(run_routes(tmp_path)).detail == "Ep.cs:1"


# --- symbols ----------------------------------------------------------------


def test_csharp_symbols_public_surface(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "Limits.cs",
        """namespace App.Core;

public class Limits
{
    public const int Max = 10;
    public const string ApiKey = "sk-live-abc123secret";
    public static readonly string Name = "n";
    public static readonly Guid Id = Guid.NewGuid();
    public readonly int inst = 2;
    public static int Mutable = 4;
    internal const int Hidden = 1;
    private static readonly int P = 3;
    protected const int Prot = 3;
    public class Nested { public const int Deep = 1; }
    internal class InternalNested { public const int Nope = 1; }
}

internal class Secret { public const int Nope = 1; }
public interface IShape { const int Sides = 4; void Draw(); }
public enum Color { Red = 0xff0000, Green, Blue = Red }
public record Point(int X, int Y);
public record struct Pair(int A, int B);
public struct Vec { public const int Dim = 3; }
public delegate void Callback(int x);
public static class Ext { public static int Twice(this int x) => x * 2; }
file class FileLocal {}
""",
    )
    write(
        tmp_path,
        "Block.cs",
        """namespace A.B
{
    public class InBlock { }
    public enum Mode { On, Off }
}
public class Global { }
""",
    )
    result = run_symbols(tmp_path)
    assert names_of(result) == sorted(
        [
            ("Limits", "class"),
            ("Limits.Max", "member"),
            ("Limits.ApiKey", "member"),
            ("Limits.Name", "member"),
            ("Limits.Id", "member"),
            ("Limits.Nested", "class"),
            ("Limits.Nested.Deep", "member"),
            ("IShape", "interface"),
            ("IShape.Sides", "member"),
            ("Color", "enum"),
            ("Color.Red", "member"),
            ("Color.Green", "member"),
            ("Color.Blue", "member"),
            ("Point", "class"),
            ("Pair", "class"),
            ("Vec", "class"),
            ("Vec.Dim", "member"),
            ("Callback", "type"),
            ("Ext", "class"),
            ("InBlock", "class"),
            ("Mode", "enum"),
            ("Mode.On", "member"),
            ("Mode.Off", "member"),
            ("Global", "class"),
        ]
    )
    (cov,) = [r for r in result.coverage if r.framework == "csharp"]
    assert cov.status == "complete"
    blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
    assert "sk-live-abc123secret" not in blob
    assert "0xff0000" not in blob


def test_csharp_partial_class_is_listed_once_per_file(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "P.cs",
        "public partial class P { public const int A = 1; }\npublic partial class P { public const int B = 2; public const int A2 = 1; }\n",
    )
    result = run_symbols(tmp_path)
    got = names_of(result)
    assert got.count(("P", "class")) == 1
    assert ("P.A", "member") in got and ("P.B", "member") in got


def test_csharp_symbols_test_projects_skipped_and_syntax_error_site(tmp_path):
    web(tmp_path)
    write(
        tmp_path,
        "src/Foo.Tests/Foo.Tests.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n<ItemGroup><PackageReference Include="xunit" Version="2.6.0" /></ItemGroup>\n</Project>\n',
    )
    write(tmp_path, "src/Foo.Tests/FooTests.cs", "public class FooTests { }\n")
    write(tmp_path, "Bad.cs", "public class Bad { public const int X = ; \n")
    result = run_symbols(tmp_path)
    rows = {r.scope: r for r in result.coverage if r.framework == "csharp"}
    assert rows["."].status == "partial" and "Bad.cs:" in rows["."].detail
    assert rows["src/Foo.Tests"].detail == "skipped 1 test"
    assert ("FooTests", "class") not in names_of(result)


# --- fix round 4 -------------------------------------------------------------

DEEP = 5000
API_PROGRAM = 'var app = WebApplication.CreateBuilder(args).Build();\napp.MapGet("/real", () => 1);\n'


def _deep(tag: str = "ItemGroup") -> str:
    return "<Project>" + f"<{tag}>" * DEEP + f"</{tag}>" * DEEP + "</Project>"


@pytest.mark.parametrize("where", ["Directory.Build.props", "src/Api/Api.csproj"])
def test_deeply_nested_msbuild_file_degrades_instead_of_aborting(tmp_path, where):
    web(tmp_path, "src/Api")
    write(tmp_path, "src/Api/Program.cs", API_PROGRAM + "public class Plan { }\n")
    write(tmp_path, where, _deep())
    if where.endswith(".csproj"):
        write(tmp_path, "src/Api/Api.csproj", _deep())
    assert paths(run_routes(tmp_path)) is not None
    assert ("Plan", "class") in names_of(run_symbols(tmp_path))


def test_unwalkable_msbuild_file_is_not_a_test_project_and_warns(tmp_path, monkeypatch):
    web(tmp_path, "src/Api")
    write(tmp_path, "src/Api/Program.cs", "public class Plan { }\n")

    def boom(*_a, **_k):
        raise RecursionError

    monkeypatch.setattr(
        "strata_kb.codeingest.extractors._cs_testproj._marks_test", boom
    )
    result = run_symbols(tmp_path)
    assert ("Plan", "class") in names_of(result)
    assert any("Api.csproj" in w for w in result.warnings)


def test_symbols_survive_test_project_detection_failing(tmp_path, monkeypatch):
    web(tmp_path)
    write(tmp_path, "Program.cs", "public class Plan { }\n")

    def boom(*_a, **_k):
        raise RuntimeError("detector")

    monkeypatch.setattr(
        "strata_kb.codeingest.extractors._cs_ast.test_project_dirs", boom
    )
    result = run_symbols(tmp_path)
    assert ("Plan", "class") in names_of(result)
    assert any("test project" in w for w in result.warnings)


def test_import_escaping_the_repo_does_not_resolve_to_a_repo_file(tmp_path):
    write(
        tmp_path,
        "Directory.Build.props",
        f"<Project><ItemGroup>{XUNIT}</ItemGroup></Project>",
    )
    write(
        tmp_path,
        "src/Directory.Build.props",
        '<Project><Import Project="$(MSBuildThisFileDirectory)../../Directory.Build.props" /></Project>',
    )
    write(tmp_path, "src/Api/Api.csproj", WEB)
    write(tmp_path, PRODUCT_API[0], PRODUCT_API[1])
    assert paths(run_routes(tmp_path)) == [("GET", "/api/u")]


def test_import_into_a_dot_directory_is_not_confused_with_a_plain_one(tmp_path):
    write(
        tmp_path,
        "eng/Directory.Build.props",
        f"<Project><ItemGroup>{XUNIT}</ItemGroup></Project>",
    )
    write(
        tmp_path,
        "src/Directory.Build.props",
        '<Project><Import Project="$(MSBuildThisFileDirectory)../.eng/Directory.Build.props" /></Project>',
    )
    write(tmp_path, "src/Api/Api.csproj", WEB)
    write(tmp_path, PRODUCT_API[0], PRODUCT_API[1])
    assert paths(run_routes(tmp_path)) == [("GET", "/api/u")]


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        # unevaluable When: Otherwise is unknown too, so nothing is a test project
        ("$(Configuration) == 'Debug'", [("GET", "/api/u"), ("GET", "/fake")]),
        # true for Api.Tests (no reference); false for Api, so Otherwise marks it
        ("$(MSBuildProjectName.EndsWith('.Tests'))", [("GET", "/fake")]),
        # false for both: Otherwise marks both as test projects
        ("$(MSBuildProjectName.EndsWith('.Nope'))", []),
    ],
)
def test_choose_otherwise_follows_its_when_conditions(tmp_path, when, expected):
    two_projects(
        tmp_path,
        f'<Project><Choose><When Condition="{when}"><ItemGroup /></When>'
        f"<Otherwise><ItemGroup>{XUNIT}</ItemGroup></Otherwise></Choose></Project>",
    )
    assert paths(run_routes(tmp_path)) == expected


def test_get_path_of_file_above_honours_the_file_it_names(tmp_path):
    write(
        tmp_path,
        "Directory.Build.props",
        f"<Project><ItemGroup>{XUNIT}</ItemGroup></Project>",
    )
    write(tmp_path, "Directory.Packages.props", "<Project></Project>")
    write(
        tmp_path,
        "src/Directory.Build.props",
        "<Project><Import Project=\"$([MSBuild]::GetPathOfFileAbove('Directory.Packages.props', '$(MSBuildThisFileDirectory)../'))\" /></Project>",
    )
    write(tmp_path, "src/Api/Api.csproj", WEB)
    write(tmp_path, PRODUCT_API[0], PRODUCT_API[1])
    assert paths(run_routes(tmp_path)) == [("GET", "/api/u")]


def test_tests_directory_of_a_non_test_project_is_product_symbols(tmp_path):
    write(tmp_path, "tests/Api.Tests/Api.Tests.csproj", WEB)
    write(tmp_path, "tests/Api.Tests/Plan.cs", "public class Plan { }\n")
    result = run_symbols(tmp_path)
    assert ("Plan", "class") in names_of(result)
    assert all("skipped" not in r.detail for r in result.coverage)
