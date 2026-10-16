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
CREATE TABLE meta (
	"key" VARCHAR NOT NULL, 
	value VARCHAR NOT NULL, 
	PRIMARY KEY ("key")
);
INSERT INTO "meta" VALUES('schema_version','3');
INSERT INTO "meta" VALUES('generation','13');
CREATE TABLE metric_points (
	id INTEGER NOT NULL, 
	run_id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	step INTEGER NOT NULL, 
	value FLOAT NOT NULL, 
	t FLOAT, 
	PRIMARY KEY (id)
);
INSERT INTO "metric_points" VALUES(1,'a','loss',0,1.0,1791288000.0);
INSERT INTO "metric_points" VALUES(2,'a','loss',1,0.5,1791288000.0);
INSERT INTO "metric_points" VALUES(3,'a','loss',2,0.25,1791288000.0);
CREATE TABLE metric_points_pending (
	run_id VARCHAR NOT NULL, 
	PRIMARY KEY (run_id)
);
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
CREATE TABLE projects (
	name VARCHAR NOT NULL, 
	repo VARCHAR NOT NULL, 
	entry_json TEXT NOT NULL, 
	PRIMARY KEY (name)
);
INSERT INTO "projects" VALUES('toy','__HX_FIXTURE_ROOT__/toy','{"project":"toy","repo":"__HX_FIXTURE_ROOT__/toy","config":{"project":"toy","description":"","datasets":{"toyset":{"version":"v1","path":"data/test.jsonl","host":"local","description":"","splits":{"test":"data/test.jsonl"},"id_field":"id","reference_field":"reference"}},"metrics":{"accuracy":{"version":"v1","fn":"toymetrics:accuracy","higher_is_better":true,"params":{},"changelog":{},"unit":""},"broken":{"version":"v1","fn":"toymetrics:broken","higher_is_better":true,"params":{},"changelog":{},"unit":""}},"tasks":{"toy-acc":{"dataset":"toyset","split":"test","metrics":["accuracy"],"primary":"accuracy","description":"","kind":"generic","views":{},"baseline":null,"version_param":"version"},"toy-broken":{"dataset":"toyset","split":"test","metrics":["accuracy","broken"],"primary":"accuracy","description":"","kind":"generic","views":{},"baseline":null,"version_param":"version"}},"stages":{"infer":"__HX_FIXTURE_PYTHON__ infer.py --ckpt {checkpoint}"},"env":{"setup":null,"python":["__HX_FIXTURE_PYTHON__"]}},"registered_at":"2026-10-16T21:27:35.337631Z","previous_repos":[],"remote_host":null}');
CREATE TABLE run_changes (
	run_id VARCHAR NOT NULL, 
	generation INTEGER NOT NULL, 
	PRIMARY KEY (run_id)
);
INSERT INTO "run_changes" VALUES('a',13);
INSERT INTO "run_changes" VALUES('b',9);
INSERT INTO "run_changes" VALUES('legacy',12);
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
	record_json TEXT NOT NULL, 
	PRIMARY KEY (run_id)
);
INSERT INTO "runs" VALUES('a','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','sha256:aaaa','c1','0d23685058ae4793bbfab827b4959dbc',NULL,0,0,'{"run_id":"a","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"0d23685058ae4793bbfab827b4959dbc","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[{"name":"toyset","version":"v1","split":"test","host":"local","path":"data/test.jsonl","hash":"sha256:605125773c56e24c54980a90b1d34857d6336a20c1068bd263a0f88fa0956c2b","hash_mode":"full","size":null,"checked_at":null}],"seed":null,"config_hash":"sha256:aaaa","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('b','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','sha256:aaaa','c1','0d23685058ae4793bbfab827b4959dbc',NULL,0,0,'{"run_id":"b","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"0d23685058ae4793bbfab827b4959dbc","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[{"name":"toyset","version":"v1","split":"test","host":"local","path":"data/test.jsonl","hash":"sha256:605125773c56e24c54980a90b1d34857d6336a20c1068bd263a0f88fa0956c2b","hash_mode":"full","size":null,"checked_at":null}],"seed":null,"config_hash":"sha256:aaaa","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
INSERT INTO "runs" VALUES('legacy','toy','toy-acc','finished','2026-10-06T12:00:00+00:00','legacy','c1','0d23685058ae4793bbfab827b4959dbc',NULL,0,0,'{"run_id":"legacy","project":"toy","task":"toy-acc","hypothesis":"","kind":"full","parent":null,"stage":null,"command":["echo","hi"],"command_template":["echo","hi"],"vars":{},"params":{},"cwd":"__HX_FIXTURE_ROOT__/toy","environment_id":"0d23685058ae4793bbfab827b4959dbc","host":"mac","executor":{"type":"local","pid":null,"pid_create_time":null,"child_pid":null,"host":null,"gpus":[],"slurm_job_id":null,"node":null,"queue_position":null},"git":{"repo":null,"commit":"c1","branch":null,"dirty":false,"diff_hash":null,"untracked_count":0,"untracked":[]},"datasets":[],"seed":null,"config_hash":"legacy","status":"finished","created_at":"2026-10-06T12:00:00Z","started_at":null,"ended_at":null,"end_reason":null,"exit_code":null,"artifacts":[],"tags":[],"starred":false,"archived":false,"created_by":"human","usage":null,"cost":null,"sweep_id":null,"gpus_requested":0}');
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
CREATE TABLE scores_stale (
	run_id VARCHAR NOT NULL, 
	PRIMARY KEY (run_id)
);
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
CREATE INDEX ix_runs_project ON runs (project);
CREATE INDEX ix_runs_parent ON runs (parent);
CREATE INDEX ix_runs_task ON runs (task);
CREATE INDEX ix_runs_created_at ON runs (created_at);
CREATE INDEX ix_runs_status ON runs (status);
CREATE INDEX ix_run_tags_tag ON run_tags (tag);
CREATE INDEX ix_scores_run_id ON scores (run_id);
CREATE INDEX ix_metric_points_run_name_step ON metric_points (run_id, name, step);
COMMIT;
