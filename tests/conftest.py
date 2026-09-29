import os
import sys
import tempfile
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

# Mock out network and LLM dependencies BEFORE they are imported
mock_module = MagicMock()
mock_module.HuggingFaceEmbeddings = MagicMock()
sys.modules['langchain_huggingface'] = mock_module
sys.modules['sentence_transformers'] = mock_module

os.environ["GROQ_API_KEY"] = "dummy_test_key"

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    import db
    original_db_path = db.DB_PATH
    db.DB_PATH = path
    
    # Initialize schema
    db.init_db()
    
    yield path
    
    # Cleanup
    db.DB_PATH = original_db_path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def app_client(setup_test_db):
    import db
    # Clear tables for each test
    with db.get_conn() as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        for table in tables:
            # sqlite_sequence is system table, don't drop it
            if table['name'] != 'sqlite_sequence':
                conn.execute(f"DROP TABLE IF EXISTS {table['name']};")
    db.init_db()
    
    from app import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
