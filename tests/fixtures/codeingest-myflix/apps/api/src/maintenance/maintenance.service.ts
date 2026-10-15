import { Cron } from '@nestjs/schedule';
export class MaintenanceService {
  @Cron('0 3 * * *')
  async createPartition() {}
}
