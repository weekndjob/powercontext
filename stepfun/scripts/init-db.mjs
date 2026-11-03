import {SeekdbAdminClient} from 'seekdb';
const name=process.env.SEEKDB_DATABASE||'stepfun_edge_2026';
if(!/^[a-zA-Z0-9_]{1,64}$/.test(name))throw Error('数据库名应为字母、数字或下划线');
const admin=new SeekdbAdminClient({host:process.env.SEEKDB_HOST||'127.0.0.1',
  port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||''});
try {
  const databases=await admin.listDatabases();
  if(!databases.some(db=>db.name===name))await admin.createDatabase(name);
  console.log('Database ready:',name);
} finally {await admin.close();}
