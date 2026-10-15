@Controller("playback")
export class PlaybackController {
  @Post("session") start(@Body() dto: StartSessionDto) {}
}
export class StartSessionDto { assetId!: string; position?: number }
