BEGIN TRANSACTION;
CREATE TABLE datasets (
	project VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	version VARCHAR NOT NULL, 
	host VARCHAR NOT NULL, 
	path VARCHAR NOT NULL, 
	PRIMARY KEY (project, name)
);
INSERT INTO "datasets" VALUES('toy','toyset','v1','local','data/test.jsonl');
CREATE TABLE host_cursors (
	host VARCHAR NOT NULL, 
	environment_id VARCHAR NOT NULL, 
	last_sequence INTEGER NOT NULL, 
	PRIMARY KEY (host, environment_id)
);
INSERT INTO "host_cursors" VALUES('fixture-host','fixture-remote',17);
INSERT INTO "host_cursors" VALUES('reserved-host','reserved-remote',0);
CREATE TABLE meta (
	"key" VARCHAR NOT NULL, 
	value VARCHAR NOT NULL, 
	PRIMARY KEY ("key")
);
INSERT INTO "meta" VALUES('schema_version','4');
INSERT INTO "meta" VALUES('generation','46');
CREATE TABLE metric_points (
	id INTEGER NOT NULL, 
	run_id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	step INTEGER NOT NULL, 
	value FLOAT NOT NULL, 
	t FLOAT, 
	PRIMARY KEY (id)
);
CREATE TABLE metric_points_pending (
	run_id VARCHAR NOT NULL, 
	PRIMARY KEY (run_id)
);
INSERT INTO "metric_points_pending" VALUES('a');
CREATE TABLE metrics (
	project VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	version VARCHAR NOT NULL, 
	fn VARCHAR NOT NULL, 
	higher_is_better BOOLEAN NOT NULL, 
	PRIMARY KEY (project, name)
);
INSERT INTO "metrics" VALUES('toy','accuracy','v1','toymetrics:accuracy',1);
INSERT INTO "metrics" VALUES('toy','broken','v1','toymetrics:broken',1);
INSERT INTO "metrics" VALUES('toy','up','v1','toymetrics:accuracy',1);
INSERT INTO "metrics" VALUES('toy','down','v1','toymetrics:accuracy',0);
INSERT INTO "metrics" VALUES('toy','latency','v1','toymetrics:accuracy',1);
CREATE TABLE projects (
	name VARCHAR NOT NULL, 
	repo VARCHAR NOT NULL, 
	entry_json TEXT NOT NULL, 
	PRIMARY KEY (name)
);
INSERT INTO "projects" VALUES('toy','__HX_FIXTURE_ROOT__/toy','{"project":"toy","repo":"__HX_FIXTURE_ROOT__/toy","config":{"project":"toy","description":"","datasets":{"toyset":{"version":"v1","path":"data/test.jsonl","host":"local","description":"","splits":{"test":"data/test.jsonl"},"id_field":"id","reference_field":"reference"}},"metrics":{"accuracy":{"version":"v1","fn":"toymetrics:accuracy","params":{},"changelog":{},"unit":""},"broken":{"version":"v1","fn":"toymetrics:broken","params":{},"changelog":{},"unit":""},"up":{"version":"v1","fn":"toymetrics:accuracy","higher_is_better":true,"params":{},"changelog":{},"unit":""},"down":{"version":"v1","fn":"toymetrics:accuracy","higher_is_better":false,"params":{},"changelog":{},"unit":""},"latency":{"version":"v1","fn":"toymetrics:accuracy","params":{},"changelog":{},"unit":""}},"tasks":{"toy-acc":{"dataset":"toyset","split":"test","metrics":["accuracy"],"primary":"accuracy","description":"","kind":"generic","views":{},"baseline":null,"version_param":"version","score_keys":null},"toy-broken":{"dataset":"toyset","split":"test","metrics":["accuracy","broken"],"primary":"accuracy","description":"","kind":"generic","views":{},"baseline":null,"version_param":"version","score_keys":null},"direction":{"dataset":"toyset","split":"test","metrics":["up","down"],"primary":"up","description":"","kind":"generic","views":{},"baseline":null,"version_param":"version","score_keys":null},"bench":{"dataset":"toyset","split":"test","metrics":["latency"],"primary":"latency/p95","description":"","kind":"system_bench","views":{},"baseline":null,"version_param":"version","score_keys":null},"matrix":{"dataset":"toyset","split":"test","metrics":["accuracy"],"primary":"accuracy/set-0.m-a.top1","description":"","kind":"generic","views":{},"baseline":null,"version_param":"version","score_keys":"{dataset}.{model}.{metric}"}},"stages":{"infer":"__HX_FIXTURE_PYTHON__ infer.py --ckpt {checkpoint}"},"env":{"setup":null,"python":["__HX_FIXTURE_PYTHON__"]}},"registered_at":"2026-10-16T21:27:35.403181Z","previous_repos":[],"remote_host":null,"config_format":2}');
CREATE TABLE run_changes (
	run_id VARCHAR NOT NULL, 
	generation INTEGER NOT NULL, 
	PRIMARY KEY (run_id)
);
INSERT INTO "run_changes" VALUES('a',15);
INSERT INTO "run_changes" VALUES('b',9);
INSERT INTO "run_changes" VALUES('legacy',12);
INSERT INTO "run_changes" VALUES('parent-child',18);
INSERT INTO "run_changes" VALUES('direction-0',23);
INSERT INTO "run_changes" VALUES('direction-1',28);
INSERT INTO "run_changes" VALUES('bench-0',32);
INSERT INTO "run_changes" VALUES('bench-1',36);
INSERT INTO "run_changes" VALUES('matrix-0',41);
INSERT INTO "run_changes" VALUES('matrix-1',46);
CREATE TABLE run_tags (
	run_id VARCHAR NOT NULL, 
	tag VARCHAR NOT NULL, 
	PRIMARY KEY (run_id, tag)
);
CREATE TABLE runs (
	run_id VARCHAR NOT NULL, 
	project VARCHAR NOT NULL, 
	task VARCHAR, 
	status VARCHAR NOT NULL, 
	created_at VARCHAR NOT NULL, 
	config_hash VARCHAR NOT NULL, 
	"commit" VARCHAR, 
	environment_id VARCHAR NOT NULL, 
	parent VARCHAR, 
	archived BOOLEAN NOT NULL, 
	starred BOOLEAN NOT NULL, 
	name VARCHAR, 
	record_json TEXT NOT NULL, 
	PRIMARY KEY (run_id)
);
INSERT INTO "runs" VALUES('a','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','sha256:aaaa','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,'wide %_ beam','{"run_id":"a","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[{"name":"toyset","version":"v1","split":"test","host":"local","path":"data/test.jsonl","hash":"sha256:605125773c56e24c54980a90b1d34857d6336a20c1068bd263a0f88fa0956c2b","hash_mode":"full","size":null,"checked_at":null}],"seed":null,"config_hash":"sha256:aaaa","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":"wide %_ beam","created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('b','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','sha256:aaaa','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"b","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[{"name":"toyset","version":"v1","split":"test","host":"local","path":"data/test.jsonl","hash":"sha256:605125773c56e24c54980a90b1d34857d6336a20c1068bd263a0f88fa0956c2b","hash_mode":"full","size":null,"checked_at":null}],"seed":null,"config_hash":"sha256:aaaa","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('legacy','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','legacy','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"legacy","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":null,"config_hash":"legacy","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('parent-child','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','parented','c1','08a5795185bb4422a4c69ca5ae63f12d','a',0,0,NULL,'{"run_id":"parent-child","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":"a","stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":null,"config_hash":"parented","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('direction-0','toy','direction','finished','2026-10-06T12:00:00+00:00','direction-0','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"direction-0","project":"toy","task":"direction","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":0,"config_hash":"direction-0","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('direction-1','toy','direction','finished','2026-10-06T12:00:00+00:00','direction-1','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"direction-1","project":"toy","task":"direction","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":1,"config_hash":"direction-1","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('bench-0','toy','bench','finished','2026-10-06T12:00:00+00:00','bench-0','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"bench-0","project":"toy","task":"bench","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":0,"config_hash":"bench-0","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('bench-1','toy','bench','finished','2026-10-06T12:00:00+00:00','bench-1','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"bench-1","project":"toy","task":"bench","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":1,"config_hash":"bench-1","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('matrix-0','toy','matrix','finished','2026-10-06T12:00:00+00:00','matrix-0','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"matrix-0","project":"toy","task":"matrix","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":0,"config_hash":"matrix-0","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('matrix-1','toy','matrix','finished','2026-10-06T12:00:00+00:00','matrix-1','c1','08a5795185bb4422a4c69ca5ae63f12d',NULL,0,0,NULL,'{"run_id":"matrix-1","project":"toy","task":"matrix","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"08a5795185bb4422a4c69ca5ae63f12d","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":1,"config_hash":"matrix-1","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"name":null,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
CREATE TABLE scores (
	id INTEGER NOT NULL, 
	run_id VARCHAR NOT NULL, 
	record_json TEXT NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "scores" VALUES(1,'a','{"metric":"accuracy","version":"v1","key":"value","value":0.75,"error":null,"source_hash":"sha256:30bca6684e8b747a","per_example_hash":"sha256:f8a464d1f0028aa38c98e3a5caac32cdae9e1900ce027dadbcfeb7b76682219c","evaluation_examples":4,"evaluation_ids_hash":"sha256:903a03ca18c11fedb2d6fc7aaee555f9732e525a680044d1bba28ae8209d3f23","created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(2,'b','{"metric":"accuracy","version":"v1","key":"value","value":1.0,"error":null,"source_hash":"sha256:30bca6684e8b747a","per_example_hash":"sha256:da381988a1793f8e55dd5ed42077d51a3d76c75e750ca2d6bd30be1820b77d0a","evaluation_examples":4,"evaluation_ids_hash":"sha256:903a03ca18c11fedb2d6fc7aaee555f9732e525a680044d1bba28ae8209d3f23","created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(3,'legacy','{"metric":"accuracy","version":"v1","key":"value","value":0.5,"error":null,"source_hash":null,"per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(4,'direction-0','{"metric":"up","version":"v1","key":"value","value":0.25,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(5,'direction-0','{"metric":"down","version":"v1","key":"value","value":0.25,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(6,'direction-0','{"metric":"up","version":"v0","key":"value","value":99.0,"error":null,"source_hash":"sha256:obsolete","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:01Z"}','2026-10-06T12:00:01+00:00');
INSERT INTO "scores" VALUES(7,'direction-1','{"metric":"up","version":"v1","key":"value","value":0.75,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(8,'direction-1','{"metric":"down","version":"v1","key":"value","value":0.75,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(9,'direction-1','{"metric":"up","version":"v0","key":"value","value":99.0,"error":null,"source_hash":"sha256:obsolete","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:01Z"}','2026-10-06T12:00:01+00:00');
INSERT INTO "scores" VALUES(10,'bench-0','{"metric":"latency","version":"v1","key":"p95","value":25.0,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(11,'bench-0','{"metric":"latency","version":"v0","key":"p95","value":99.0,"error":null,"source_hash":"sha256:obsolete","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:01Z"}','2026-10-06T12:00:01+00:00');
INSERT INTO "scores" VALUES(12,'bench-1','{"metric":"latency","version":"v1","key":"p95","value":75.0,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(13,'bench-1','{"metric":"latency","version":"v0","key":"p95","value":99.0,"error":null,"source_hash":"sha256:obsolete","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:01Z"}','2026-10-06T12:00:01+00:00');
INSERT INTO "scores" VALUES(14,'matrix-0','{"metric":"accuracy","version":"v1","key":"set-0.m-a.top1","value":0.25,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(15,'matrix-0','{"metric":"accuracy","version":"v1","key":"set-1.m-a.top1","value":0.125,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(16,'matrix-0','{"metric":"accuracy","version":"v0","key":"set-0.m-a.top1","value":99.0,"error":null,"source_hash":"sha256:obsolete","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:01Z"}','2026-10-06T12:00:01+00:00');
INSERT INTO "scores" VALUES(17,'matrix-1','{"metric":"accuracy","version":"v1","key":"set-0.m-a.top1","value":0.75,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(18,'matrix-1','{"metric":"accuracy","version":"v1","key":"set-1.m-a.top1","value":0.375,"error":null,"source_hash":"sha256:synthetic","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:00Z"}','2026-10-06T12:00:00+00:00');
INSERT INTO "scores" VALUES(19,'matrix-1','{"metric":"accuracy","version":"v0","key":"set-0.m-a.top1","value":99.0,"error":null,"source_hash":"sha256:obsolete","per_example_hash":null,"evaluation_examples":null,"evaluation_ids_hash":null,"created_at":"2026-10-06T12:00:01Z"}','2026-10-06T12:00:01+00:00');
CREATE TABLE scores_stale (
	run_id VARCHAR NOT NULL, 
	PRIMARY KEY (run_id)
);
INSERT INTO "scores_stale" VALUES('legacy');
CREATE TABLE tasks (
	project VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	dataset VARCHAR NOT NULL, 
	split VARCHAR, 
	"primary" VARCHAR NOT NULL, 
	metrics_json TEXT NOT NULL, 
	PRIMARY KEY (project, name)
);
INSERT INTO "tasks" VALUES('toy','toy-acc','toyset','test','accuracy','["accuracy"]');
INSERT INTO "tasks" VALUES('toy','toy-broken','toyset','test','accuracy','["accuracy", "broken"]');
INSERT INTO "tasks" VALUES('toy','direction','toyset','test','up','["up", "down"]');
INSERT INTO "tasks" VALUES('toy','bench','toyset','test','latency/p95','["latency"]');
INSERT INTO "tasks" VALUES('toy','matrix','toyset','test','accuracy/set-0.m-a.top1','["accuracy"]');
CREATE INDEX ix_runs_status ON runs (status);
CREATE INDEX ix_runs_project ON runs (project);
CREATE INDEX ix_runs_task ON runs (task);
CREATE INDEX ix_runs_parent ON runs (parent);
CREATE INDEX ix_runs_name ON runs (name);
CREATE INDEX ix_runs_created_at ON runs (created_at);
CREATE INDEX ix_run_tags_tag ON run_tags (tag);
CREATE INDEX ix_scores_run_id ON scores (run_id);
CREATE INDEX ix_metric_points_run_name_step ON metric_points (run_id, name, step);
COMMIT;
