/** Existing PDCA inference only. No fetch, database, receipt, deployment or file writes. */
import {assertFacts} from '../workers/boat_nonvercel_core.mjs';
import {buildChallenger} from '../workers/boat_pdca_shadow.mjs';

const MAX_INPUT=2*1024*1024;
try {
 const chunks=[];let size=0;
 for await (const part of process.stdin) {
  size+=part.length;if(size>MAX_INPUT)throw Error('bounded input required');chunks.push(part);
 }
 const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
 if(!input || Array.isArray(input) || Object.keys(input).sort().join(',')!=='facts,now,rows'
    ||typeof input.now!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(input.now)
    ||!Number.isFinite(Date.parse(input.now)))throw Error('exact input required');
 assertFacts(input.facts,Date.parse(input.now));
 const result=await buildChallenger(input.facts,input.rows);
 process.stdout.write(JSON.stringify(result)+'\n');
} catch {
 process.stdout.write('{"status":"PDCA_OFFLINE_REJECTED"}\n');
 process.exitCode=2;
}
