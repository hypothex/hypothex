BEGIN TRANSACTION;
CREATE TABLE event_keys (
  key TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL
);
CREATE TABLE events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  project TEXT,
  run_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
INSERT INTO "events" VALUES(1,'run.created','toy','a','{"status": "finished"}','2026-10-16T21:27:35.075688+00:00');
INSERT INTO "events" VALUES(2,'run.score_added','toy','a','{"metric": "accuracy", "version": "v1", "key": "value", "value": 0.75, "error": null, "source_hash": "sha256:30bca6684e8b747a", "per_example_hash": "sha256:f8a464d1f0028aa38c98e3a5caac32cdae9e1900ce027dadbcfeb7b76682219c", "evaluation_examples": 4, "evaluation_ids_hash": "sha256:903a03ca18c11fedb2d6fc7aaee555f9732e525a680044d1bba28ae8209d3f23", "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.211679+00:00');
INSERT INTO "events" VALUES(3,'run.created','toy','b','{"status": "finished"}','2026-10-16T21:27:35.217740+00:00');
INSERT INTO "events" VALUES(4,'run.score_added','toy','b','{"metric": "accuracy", "version": "v1", "key": "value", "value": 1.0, "error": null, "source_hash": "sha256:30bca6684e8b747a", "per_example_hash": "sha256:da381988a1793f8e55dd5ed42077d51a3d76c75e750ca2d6bd30be1820b77d0a", "evaluation_examples": 4, "evaluation_ids_hash": "sha256:903a03ca18c11fedb2d6fc7aaee555f9732e525a680044d1bba28ae8209d3f23", "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.335068+00:00');
INSERT INTO "events" VALUES(5,'run.created','toy','legacy','{"status": "finished"}','2026-10-16T21:27:35.340547+00:00');
INSERT INTO "events" VALUES(6,'run.score_added','toy','legacy','{"metric": "accuracy", "version": "v1", "key": "value", "value": 0.5, "error": null, "source_hash": null, "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.342094+00:00');
CREATE TABLE receipts (
  command_id TEXT PRIMARY KEY,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE sweep_issuance (
  operation_key TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  sweep_id TEXT,
  episode INTEGER NOT NULL,
  revision INTEGER NOT NULL,
  state TEXT NOT NULL,
  data TEXT NOT NULL,
  UNIQUE(project, sweep_id, episode)
);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('events',6);
COMMIT;
