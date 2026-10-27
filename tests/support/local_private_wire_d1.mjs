// Test-only native SQLite adapter. No listener, credentials or remote fallback.
import {DatabaseSync} from 'node:sqlite';
import {lstatSync} from 'node:fs';
import path from 'node:path';

function localPath(filename){
  if(typeof filename!=='string'||/^(?:\\\\|\/\/|[A-Za-z]+:\/\/)/.test(filename))throw Error('LOCAL_TEST_PATH');
  const absolute=path.resolve(filename);
  if(absolute.startsWith('\\\\')||absolute.startsWith('//')||absolute.slice(path.parse(absolute).root.length).includes(':'))throw Error('LOCAL_TEST_PATH');
  const root=path.parse(absolute).root,parts=absolute.slice(root.length).split(path.sep);
  let current=root;
  for(let i=-1;i<parts.length;i++){
    if(i>=0)current=path.join(current,parts[i]);
    const stat=lstatSync(current,{throwIfNoEntry:false});
    if(stat?.isSymbolicLink())throw Error('LOCAL_TEST_PATH');
    if(i<parts.length-1){
      if(!stat?.isDirectory()||lstatSync(path.join(current,'.git'),{throwIfNoEntry:false}))throw Error('LOCAL_TEST_PATH');
    }else if(stat&&(!stat.isFile()||stat.nlink!==1))throw Error('LOCAL_TEST_PATH');
  }
  for(const suffix of ['-journal','-wal','-shm']){
    const stat=lstatSync(absolute+suffix,{throwIfNoEntry:false});
    if(stat&&(stat.isSymbolicLink()||!stat.isFile()||stat.nlink!==1))throw Error('LOCAL_TEST_PATH');
  }
  return absolute;
}
export function openLocalPrivateWireD1(filename,options={}){
  let closed=false;
  const stats={prepare:0,batch:0,readBatches:0,writeBatches:0,statements:0,bodyBytesMaterialized:0,maxBodyBytesMaterialized:0};
  const binding={stats,
    prepare(sql){
      stats.prepare++;
      const make=params=>({sql,params,owner:binding,bind:(...values)=>make(values)});
      return make([]);
    },
    async batch(statements){
      stats.batch++;
      if(closed||!Array.isArray(statements)||!statements.length||statements.length>20||statements.some(s=>s.owner!==binding))throw Error('LOCAL_TEST_BATCH');
      const writable=statements.some(s=>!/^SELECT\s/i.test(s.sql));
      stats[writable?'writeBatches':'readBatches']++;
      const file=localPath(filename),db=new DatabaseSync(file,{readOnly:!writable});
      try{
        db.exec('PRAGMA foreign_keys=ON');
        db.exec('PRAGMA busy_timeout=15000');
        options.beforeBegin?.({db,writable});
        db.exec(writable?'BEGIN IMMEDIATE':'BEGIN');
        const result=[];
        for(let index=0;index<statements.length;index++){
          const s=statements[index];
          options.beforeStatement?.({index,sql:s.sql,params:s.params,db,writable});
          const query=db.prepare(s.sql);let rows=[],changes=0;
          if(query.columns().length)rows=query.all(...s.params);
          else changes=Number(query.run(...s.params).changes);
          stats.statements++;
          for(const row of rows)if(row.body instanceof Uint8Array){stats.bodyBytesMaterialized+=row.body.length;stats.maxBodyBytesMaterialized=Math.max(stats.maxBodyBytesMaterialized,row.body.length);}
          result.push({success:true,results:rows,meta:{changes}});
          options.afterStatement?.({index,sql:s.sql,params:s.params,db,writable});
        }
        options.beforeCommit?.({db,writable});
        db.exec('COMMIT');
        options.afterCommit?.({db,writable});
        return result;
      }catch(error){if(db.isTransaction)db.exec('ROLLBACK');throw error;}
      finally{db.close();}
    },
    close(){closed=true;}
  };
  return binding;
}
