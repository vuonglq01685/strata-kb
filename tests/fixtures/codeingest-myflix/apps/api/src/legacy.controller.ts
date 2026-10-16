const V = "v1";
@Controller("legacy")
export class LegacyController {
  @Get(`${V}/x`) x() {}
}
