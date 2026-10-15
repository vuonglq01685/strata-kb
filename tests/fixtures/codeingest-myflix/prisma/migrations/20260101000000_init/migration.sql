CREATE TABLE "playback_events" ("id" BIGINT, "created_at" TIMESTAMPTZ, PRIMARY KEY ("id","created_at")) PARTITION BY RANGE ("created_at");
CREATE INDEX "playback_events_created_at_idx" ON "playback_events" ("created_at");
