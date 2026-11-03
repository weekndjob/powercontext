"""Import explicitly synthetic samples; repeated runs keep existing samples."""
import json
from pathlib import Path
from database import get_db_connection, init_database_schema
from models import MaterialCreate

def main():
    init_database_schema()
    samples = json.loads((Path(__file__).parent / 'samples/sample_materials.json').read_text(encoding='utf-8'))
    inserted = 0
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            for row in samples:
                sample = MaterialCreate(**row)
                cursor.execute('SELECT id FROM materials WHERE title=%s AND source=%s LIMIT 1', (sample.title, sample.source))
                if cursor.fetchone():
                    continue
                cursor.execute('INSERT INTO materials(title,content,source,tags) VALUES (%s,%s,%s,%s)', (sample.title,sample.content,sample.source,sample.tags))
                inserted += 1
    print(f'Imported {inserted} synthetic samples')

if __name__ == '__main__':
    main()
