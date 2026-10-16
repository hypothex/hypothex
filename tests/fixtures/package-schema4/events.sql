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
INSERT INTO "events" VALUES(1,'run.created','toy','a','{"status": "finished"}','2026-10-16T21:27:35.075661+00:00');
INSERT INTO "events" VALUES(2,'run.score_added','toy','a','{"metric": "accuracy", "version": "v1", "key": "value", "value": 0.75, "error": null, "source_hash": "sha256:30bca6684e8b747a", "per_example_hash": "sha256:f8a464d1f0028aa38c98e3a5caac32cdae9e1900ce027dadbcfeb7b76682219c", "evaluation_examples": 4, "evaluation_ids_hash": "sha256:903a03ca18c11fedb2d6fc7aaee555f9732e525a680044d1bba28ae8209d3f23", "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.213614+00:00');
INSERT INTO "events" VALUES(3,'run.created','toy','b','{"status": "finished"}','2026-10-16T21:27:35.219355+00:00');
INSERT INTO "events" VALUES(4,'run.score_added','toy','b','{"metric": "accuracy", "version": "v1", "key": "value", "value": 1.0, "error": null, "source_hash": "sha256:30bca6684e8b747a", "per_example_hash": "sha256:da381988a1793f8e55dd5ed42077d51a3d76c75e750ca2d6bd30be1820b77d0a", "evaluation_examples": 4, "evaluation_ids_hash": "sha256:903a03ca18c11fedb2d6fc7aaee555f9732e525a680044d1bba28ae8209d3f23", "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.334748+00:00');
INSERT INTO "events" VALUES(5,'run.created','toy','legacy','{"status": "finished"}','2026-10-16T21:27:35.340330+00:00');
INSERT INTO "events" VALUES(6,'run.score_added','toy','legacy','{"metric": "accuracy", "version": "v1", "key": "value", "value": 0.5, "error": null, "source_hash": null, "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.341783+00:00');
INSERT INTO "events" VALUES(7,'run.renamed','toy','a','{"status": "finished", "name": "wide %_ beam"}','2026-10-16T21:27:35.352645+00:00');
INSERT INTO "events" VALUES(8,'run.created','toy','parent-child','{"status": "finished"}','2026-10-16T21:27:35.357600+00:00');
INSERT INTO "events" VALUES(9,'run.created','toy','direction-0','{"status": "finished"}','2026-10-16T21:27:35.365374+00:00');
INSERT INTO "events" VALUES(10,'run.score_added','toy','direction-0','{"metric": "up", "version": "v1", "key": "value", "value": 0.25, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.366968+00:00');
INSERT INTO "events" VALUES(11,'run.score_added','toy','direction-0','{"metric": "down", "version": "v1", "key": "value", "value": 0.25, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.368359+00:00');
INSERT INTO "events" VALUES(12,'run.score_added','toy','direction-0','{"metric": "up", "version": "v0", "key": "value", "value": 99.0, "error": null, "source_hash": "sha256:obsolete", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:01Z"}','2026-10-16T21:27:35.369594+00:00');
INSERT INTO "events" VALUES(13,'run.created','toy','direction-1','{"status": "finished"}','2026-10-16T21:27:35.374531+00:00');
INSERT INTO "events" VALUES(14,'run.score_added','toy','direction-1','{"metric": "up", "version": "v1", "key": "value", "value": 0.75, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.375812+00:00');
INSERT INTO "events" VALUES(15,'run.score_added','toy','direction-1','{"metric": "down", "version": "v1", "key": "value", "value": 0.75, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.376876+00:00');
INSERT INTO "events" VALUES(16,'run.score_added','toy','direction-1','{"metric": "up", "version": "v0", "key": "value", "value": 99.0, "error": null, "source_hash": "sha256:obsolete", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:01Z"}','2026-10-16T21:27:35.377940+00:00');
INSERT INTO "events" VALUES(17,'run.created','toy','bench-0','{"status": "finished"}','2026-10-16T21:27:35.382630+00:00');
INSERT INTO "events" VALUES(18,'run.score_added','toy','bench-0','{"metric": "latency", "version": "v1", "key": "p95", "value": 25.0, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.383866+00:00');
INSERT INTO "events" VALUES(19,'run.score_added','toy','bench-0','{"metric": "latency", "version": "v0", "key": "p95", "value": 99.0, "error": null, "source_hash": "sha256:obsolete", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:01Z"}','2026-10-16T21:27:35.384900+00:00');
INSERT INTO "events" VALUES(20,'run.created','toy','bench-1','{"status": "finished"}','2026-10-16T21:27:35.389792+00:00');
INSERT INTO "events" VALUES(21,'run.score_added','toy','bench-1','{"metric": "latency", "version": "v1", "key": "p95", "value": 75.0, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.390995+00:00');
INSERT INTO "events" VALUES(22,'run.score_added','toy','bench-1','{"metric": "latency", "version": "v0", "key": "p95", "value": 99.0, "error": null, "source_hash": "sha256:obsolete", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:01Z"}','2026-10-16T21:27:35.391972+00:00');
INSERT INTO "events" VALUES(23,'run.created','toy','matrix-0','{"status": "finished"}','2026-10-16T21:27:35.396801+00:00');
INSERT INTO "events" VALUES(24,'run.score_added','toy','matrix-0','{"metric": "accuracy", "version": "v1", "key": "set-0.m-a.top1", "value": 0.25, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.397937+00:00');
INSERT INTO "events" VALUES(25,'run.score_added','toy','matrix-0','{"metric": "accuracy", "version": "v1", "key": "set-1.m-a.top1", "value": 0.125, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.399246+00:00');
INSERT INTO "events" VALUES(26,'run.score_added','toy','matrix-0','{"metric": "accuracy", "version": "v0", "key": "set-0.m-a.top1", "value": 99.0, "error": null, "source_hash": "sha256:obsolete", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:01Z"}','2026-10-16T21:27:35.400621+00:00');
INSERT INTO "events" VALUES(27,'run.created','toy','matrix-1','{"status": "finished"}','2026-10-16T21:27:35.405566+00:00');
INSERT INTO "events" VALUES(28,'run.score_added','toy','matrix-1','{"metric": "accuracy", "version": "v1", "key": "set-0.m-a.top1", "value": 0.75, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.407320+00:00');
INSERT INTO "events" VALUES(29,'run.score_added','toy','matrix-1','{"metric": "accuracy", "version": "v1", "key": "set-1.m-a.top1", "value": 0.375, "error": null, "source_hash": "sha256:synthetic", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:00Z"}','2026-10-16T21:27:35.408375+00:00');
INSERT INTO "events" VALUES(30,'run.score_added','toy','matrix-1','{"metric": "accuracy", "version": "v0", "key": "set-0.m-a.top1", "value": 99.0, "error": null, "source_hash": "sha256:obsolete", "per_example_hash": null, "evaluation_examples": null, "evaluation_ids_hash": null, "created_at": "2026-10-06T12:00:01Z"}','2026-10-16T21:27:35.409398+00:00');
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
INSERT INTO "sqlite_sequence" VALUES('events',30);
COMMIT;
