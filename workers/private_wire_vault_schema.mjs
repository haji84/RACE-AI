// Fixed local-candidate SQL; not a cloud migration or independently locked vault.
export const OBJECTS='private_wire_objects_v1', CHUNKS='private_wire_chunks_v1';
export const APPLICATION_ID=0x52565731, VERSION=1;
const hex=name=>`typeof(${name})='text' AND length(${name})=64 AND ${name} NOT GLOB '*[^0-9a-f]*'`;
export const DEFINITIONS=[
  ['table',OBJECTS,`CREATE TABLE ${OBJECTS}(locator TEXT PRIMARY KEY CHECK(${hex('locator')}),claim_json TEXT NOT NULL CHECK(typeof(claim_json)='text' AND length(CAST(claim_json AS BLOB)) BETWEEN 1 AND 8192),wire_sha256 TEXT NOT NULL CHECK(${hex('wire_sha256')}),wire_bytes INTEGER NOT NULL CHECK(typeof(wire_bytes)='integer' AND wire_bytes BETWEEN 1 AND 4194304),chunk_count INTEGER NOT NULL CHECK(typeof(chunk_count)='integer' AND chunk_count=(wire_bytes+524287)/524288))`],
  ['table',CHUNKS,`CREATE TABLE ${CHUNKS}(locator TEXT NOT NULL REFERENCES ${OBJECTS}(locator),ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 7),chunk_sha256 TEXT NOT NULL CHECK(${hex('chunk_sha256')}),body BLOB NOT NULL CHECK(typeof(body)='blob' AND length(body) BETWEEN 1 AND 524288),PRIMARY KEY(locator,ordinal))`],
  ...[OBJECTS,CHUNKS].flatMap(table=>['UPDATE','DELETE'].map(verb=>['trigger',`${table}_no_${verb.toLowerCase()}`,`CREATE TRIGGER ${table}_no_${verb.toLowerCase()} BEFORE ${verb} ON ${table} BEGIN SELECT RAISE(ABORT,'LOCAL_VAULT_IMMUTABLE'); END`])),
  ['trigger',`${OBJECTS}_no_conflict`,`CREATE TRIGGER ${OBJECTS}_no_conflict BEFORE INSERT ON ${OBJECTS} WHEN EXISTS(SELECT 1 FROM ${OBJECTS} WHERE locator=NEW.locator AND NOT (claim_json IS NEW.claim_json AND wire_sha256 IS NEW.wire_sha256 AND wire_bytes IS NEW.wire_bytes AND chunk_count IS NEW.chunk_count)) BEGIN SELECT RAISE(ABORT,'LOCAL_VAULT_IMMUTABLE'); END`],
  ['trigger',`${CHUNKS}_no_reinsert`,`CREATE TRIGGER ${CHUNKS}_no_reinsert BEFORE INSERT ON ${CHUNKS} WHEN EXISTS(SELECT 1 FROM ${CHUNKS} WHERE locator=NEW.locator AND ordinal=NEW.ordinal) BEGIN SELECT RAISE(ABORT,'LOCAL_VAULT_IMMUTABLE'); END`],
  ['trigger',`${OBJECTS}_cap`,`CREATE TRIGGER ${OBJECTS}_cap BEFORE INSERT ON ${OBJECTS} WHEN NOT EXISTS(SELECT 1 FROM ${OBJECTS} WHERE locator=NEW.locator) AND ((SELECT count(*) FROM ${OBJECTS})>=32 OR (SELECT coalesce(sum(wire_bytes),0) FROM ${OBJECTS})+NEW.wire_bytes>16777216) BEGIN SELECT RAISE(ABORT,'LOCAL_VAULT_CAP'); END`],
  ['trigger',`${CHUNKS}_range`,`CREATE TRIGGER ${CHUNKS}_range BEFORE INSERT ON ${CHUNKS} WHEN NOT EXISTS(SELECT 1 FROM ${OBJECTS} WHERE locator=NEW.locator AND NEW.ordinal<chunk_count AND length(NEW.body)=min(524288,wire_bytes-NEW.ordinal*524288)) BEGIN SELECT RAISE(ABORT,'LOCAL_VAULT_CHUNK'); END`]
];
const literal=value=>"'"+value.replaceAll("'","''")+"'";
const visible="name NOT GLOB 'sqlite_*'";
const entries=DEFINITIONS.map(([type,name,sql])=>`(type=${literal(type)} AND name=${literal(name)} AND sql=${literal(sql)})`).join(' OR ');
export const KNOWN=`(SELECT count(*) FROM sqlite_schema WHERE ${visible})=${DEFINITIONS.length} AND NOT EXISTS(SELECT 1 FROM sqlite_schema WHERE ${visible} AND NOT (${entries})) AND (SELECT application_id FROM pragma_application_id)=${APPLICATION_ID} AND (SELECT user_version FROM pragma_user_version)=${VERSION}`;
const EMPTY=`NOT EXISTS(SELECT 1 FROM sqlite_schema WHERE ${visible}) AND (SELECT application_id FROM pragma_application_id)=0 AND (SELECT user_version FROM pragma_user_version)=0`;
export const CLASSIFY=`SELECT CASE WHEN (${KNOWN}) THEN 'known' WHEN (${EMPTY}) THEN 'empty' ELSE 'foreign' END AS state`;
export const guard=allowEmpty=>`SELECT CASE WHEN ((${KNOWN})${allowEmpty?` OR (${EMPTY})`:''}) THEN 1 ELSE abs(-9223372036854775808) END AS admitted`;
export const INITIALIZE=DEFINITIONS.map(([, ,sql])=>sql.replace(/^CREATE (TABLE|TRIGGER) /,'CREATE $1 IF NOT EXISTS ')).concat([`PRAGMA application_id=${APPLICATION_ID}`,`PRAGMA user_version=${VERSION}`]);
