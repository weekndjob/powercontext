"""Independent checks of Qoder's application against actual SeekDB and HTTP."""
import datetime as dt
import json
import os
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pymysql

app_dir = Path(__file__).resolve().parent
evidence = app_dir / 'evidence'
evidence.mkdir(exist_ok=True)
from database import DatabaseConfig
config = DatabaseConfig()
import sys
import socket
python = sys.executable
with socket.socket() as probe:
    assert probe.connect_ex(('127.0.0.1', 18080)) != 0, 'Verification port 18080 is already occupied'
log = (evidence / 'acceptance-server.log').open('a', encoding='utf-8')
server = None
report = {'started_at': dt.datetime.now().astimezone().isoformat(), 'checks': [], 'responses': {}}
materials, todos = [], []
client = httpx.Client(base_url='http://127.0.0.1:18080', timeout=30)

def check(name, condition, detail=None):
    report['checks'].append({'name': name, 'passed': bool(condition), 'detail': detail})
    assert condition, f'{name}: {detail}'

def request(method, path, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    check(method + ' ' + path, response.status_code == expected, {'status': response.status_code, 'body': response.text[:500] if response.status_code != expected else None})
    return response.json()

def start():
    global server
    server = subprocess.Popen([python, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '18080'], cwd=app_dir, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
    for _ in range(90):
        assert server.poll() is None, 'App failed to start; inspect independent-server.log'
        try:
            response = client.get('/api/health')
            if response.status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise RuntimeError('App readiness timed out')

def stop():
    if server and server.poll() is None:
        server.terminate()
        server.wait(timeout=20)

try:
    start()
    for page in ('/', '/materials', '/search', '/todos', '/summary'):
        response = client.get(page)
        check('HTML ' + page, response.status_code == 200 and '研途' in response.text)
    conn = pymysql.connect(host=config.host, port=config.port, user=config.user, password=config.password, database=config.database, charset='utf8mb4', autocommit=True, read_timeout=20)
    with conn.cursor() as cur:
        cur.execute('SELECT VERSION()')
        report['database_version'] = cur.fetchone()[0]
        cur.execute('SHOW CREATE TABLE materials')
        ddl = cur.fetchone()[1]
        report['materials_ddl'] = ddl
        check('Native IK fulltext index', 'FULLTEXT' in ddl.upper() and 'ik' in ddl.lower())
    for index, content in enumerate(('测试样例：科研知识检索 数据库 quasar research retrieval', '测试样例：quasar experimental protocol', '测试样例：biology microscope experiment')):
        title = "测试样例 ');window.__qoder_xss=1;//" if index == 0 else '独立验收测试样例 ' + str(index)
        data = request('POST', '/api/materials', json={'title': title, 'content': content, 'source': 'independent-acceptance-only', 'tags': '科研, 端到端,科研' if index == 0 else '独立验收'})
        materials.append(data['data']['id'])
    wide_content = '科研🙂' * 16000
    data = request('POST', '/api/materials', json={'title': '多字节正文边界测试样例', 'content': wide_content, 'source': 'independent-acceptance-only'})
    materials.append(data['data']['id'])
    stored = request('GET', f'/api/materials/{materials[-1]}')
    check('48000 Unicode characters above 64 KiB persist', stored['content'] == wide_content and len(wide_content.encode('utf-8')) > 65535)
    result = request('POST', '/api/search', json={'query': 'quasar', 'tags': '', 'page': 1, 'page_size': 100})
    ids = {m['id'] for m in result['materials']}
    check('English fulltext selects matching documents', set(materials[:2]).issubset(ids) and materials[2] not in ids)
    result = request('GET', '/api/search', params={'q': '科研', 'tags': '端到端'})
    check('Chinese fulltext and normalized complete tag', materials[0] in {m['id'] for m in result['materials']})
    report['responses']['chinese_search'] = result
    result = request('GET', '/api/search', params={'q': 'nonexistentwordzxqv'})
    check('No match is empty', result['total'] == 0 and result['materials'] == [])
    result = request('GET', '/api/search', params={'q': '', 'tags': '端到'})
    check('Tag matches whole tag', materials[0] not in {m['id'] for m in result['materials']})
    result = request('GET', '/api/search', params={'q': "' OR 1=1 --", 'tags': "__absent_tag' OR 1=1 --"})
    check('Query remains a bound SQL parameter', result['total'] == 0)
    result = request('POST', '/api/materials/import', data={'title': '导入测试样例', 'source': 'UTF8 file', 'tags': '测试, 导入'}, files={'file': ('notes.md', '\ufeff测试样例：科研资料 fileimporttoken'.encode('utf-8'), 'text/markdown')})
    materials.append(result['data']['id'])
    stored = request('GET', f'/api/materials/{materials[-1]}')
    check('UTF8 Markdown import and BOM removal', stored['content'].startswith('测试样例') and stored['tags'] == '测试,导入')
    request('POST', '/api/materials/import', expected=400, data={'title': 'bad encoding'}, files={'file': ('bad.txt', b'\xff\xfe', 'text/plain')})
    request('POST', '/api/materials/import', expected=400, data={'title': 'bad extension'}, files={'file': ('bad.exe', b'not executable', 'application/octet-stream')})
    request('POST', '/api/materials/import', expected=422, data={'title': 'oversized metadata', 'source': 's' * 1001}, files={'file': ('notes.md', b'valid content', 'text/markdown')})
    request('POST', '/api/materials/import', expected=400, data={'title': 'oversized file'}, files={'file': ('huge.txt', b'x' * (2 * 1024 * 1024 + 1), 'text/plain')})
    request('POST', '/api/materials', expected=422, json={'title': '   ', 'content': 'valid'})
    request('POST', '/api/materials', expected=422, json={'title': 'valid', 'content': '   '})
    request('POST', '/api/todos', expected=422, json={'title': 'invalid', 'material_id': 0})
    todo = request('POST', '/api/todos', json={'title': '完成独立验收（测试样例）', 'material_id': materials[0], 'due_date': dt.date.today().isoformat()})
    todos.append(todo['data']['id'])
    request('PUT', f'/api/todos/{todos[0]}', json={'completed': True})
    request('PUT', f'/api/todos/{todos[0]}', json={'completed': True, 'title': '同一状态下仍可修改标题（测试样例）'})
    request('PUT', f'/api/todos/{todos[0]}', json={'completed': True})
    request('PUT', f'/api/todos/{todos[0]}', json={'material_id': None, 'due_date': None})
    result = request('GET', '/api/todos')
    stored = next(t for t in result['todos'] if t['id'] == todos[0])
    check('Task status, same-status edit and nullable fields', stored['completed'] and stored['material_id'] is None and stored['due_date'] is None and stored['title'] == '同一状态下仍可修改标题（测试样例）')
    linked = request('POST', '/api/todos', json={'title': '删除关联测试样例', 'material_id': materials[1]})
    todos.append(linked['data']['id'])
    request('DELETE', f'/api/materials/{materials[1]}')
    row = next(t for t in request('GET', '/api/todos')['todos'] if t['id'] == todos[-1])
    check('Deleting material clears existing task association', row['material_id'] is None)
    for attempt in range(3):
        material = request('POST', '/api/materials', json={'title': '并发关联测试样例', 'content': '仅用于验证关联一致性'})
        material_id = material['data']['id']
        materials.append(material_id)
        barrier = threading.Barrier(2)
        def create_link():
            barrier.wait()
            return client.post('/api/todos', json={'title': '并发测试样例', 'material_id': material_id})
        def remove_material():
            barrier.wait()
            return client.delete(f'/api/materials/{material_id}')
        with ThreadPoolExecutor(max_workers=2) as executor:
            creating = executor.submit(create_link)
            removing = executor.submit(remove_material)
            created, removed = creating.result(), removing.result()
        check('Concurrent material delete ' + str(attempt), removed.status_code == 200)
        check('Concurrent todo create ' + str(attempt), created.status_code in (200, 400))
        if created.status_code == 200:
            linked_id = created.json()['data']['id']
            todos.append(linked_id)
            row = next(t for t in request('GET', '/api/todos')['todos'] if t['id'] == linked_id)
            check('No orphan after concurrent delete ' + str(attempt), row['material_id'] is None)
    with conn.cursor() as cur:
        cur.execute('UPDATE materials SET created_at=%s WHERE id=%s', ('2000-01-01 12:00:00', materials[2]))
    result = request('POST', '/api/summary', json={'start_date': '2000-01-01', 'end_date': '2000-01-01'})
    check('Date range applies to totals', result['total_materials'] == 1 and result['total_todos'] == 0, result)
    report['responses']['dated_summary'] = result
    response = client.post('/api/summary', json={'start_date': '2026-11-03', 'end_date': '2000-01-01'})
    check('Reject reversed date range', response.status_code in (400, 422))
    stop()
    start()
    stored = request('GET', f'/api/materials/{materials[0]}')
    check('Document survives application restart', stored['source'] == 'independent-acceptance-only')
    stored = next(t for t in request('GET', '/api/todos')['todos'] if t['id'] == todos[0])
    check('Completed task survives application restart', stored['completed'])
    report['status'] = 'passed'
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = str(exc)
    raise
finally:
    for item in todos:
        try:
            client.delete(f'/api/todos/{item}')
        except httpx.HTTPError:
            pass
    for item in materials:
        try:
            client.delete(f'/api/materials/{item}')
        except httpx.HTTPError:
            pass
    stop()
    client.close()
    log.close()
    report['finished_at'] = dt.datetime.now().astimezone().isoformat()
    (evidence / 'independent-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'error': report.get('error')}, ensure_ascii=False))
