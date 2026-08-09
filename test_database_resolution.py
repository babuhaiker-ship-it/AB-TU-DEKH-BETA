import sys
from unittest.mock import MagicMock

# Create a robust mock for pymongo to prevent any actual network connections on import
mock_pymongo = MagicMock()
mock_client = MagicMock()
mock_db = MagicMock()
mock_collection = MagicMock()

mock_pymongo.MongoClient.return_value = mock_client
mock_client.__getitem__.return_value = mock_db
mock_db.__getitem__.return_value = mock_collection

# Inject mock_pymongo into sys.modules before importing bot
sys.modules['pymongo'] = mock_pymongo

# Set up dummy environment variables for bot imports
import os
os.environ['BOT_TOKEN'] = 'foo'
os.environ['API_ID'] = '123'
os.environ['API_HASH'] = 'bar'
os.environ['BOT_USERNAME'] = 'baz'
os.environ['MONGO_URI'] = 'mongodb://dummy_host:27017'
os.environ['MONGO_DB_NAME'] = 'configured_test_db'

# Now import the resolution function from bot
from bot import resolve_database_name

def test_resolve_database_exact_match():
    client = MagicMock()
    client.list_database_names.return_value = ['admin', 'local', 'config', 'my_app_db', 'other_db']

    resolved = resolve_database_name(client, 'my_app_db')
    assert resolved == 'my_app_db'

def test_resolve_database_case_insensitive_match():
    client = MagicMock()
    client.list_database_names.return_value = ['admin', 'local', 'config', 'My_App_Db', 'other_db']

    resolved = resolve_database_name(client, 'my_app_db')
    assert resolved == 'My_App_Db'

def test_resolve_database_partial_match():
    client = MagicMock()
    client.list_database_names.return_value = ['admin', 'local', 'config', 'my_app_db_v1', 'other_db']

    resolved = resolve_database_name(client, 'my_app_db')
    assert resolved == 'my_app_db_v1'

def test_resolve_database_no_match_but_existing_user_db():
    client = MagicMock()
    client.list_database_names.return_value = ['admin', 'local', 'config', 'some_existing_db']

    resolved = resolve_database_name(client, 'non_existent_configured_db')
    assert resolved == 'some_existing_db'

def test_resolve_database_no_existing_user_db():
    client = MagicMock()
    client.list_database_names.return_value = ['admin', 'local', 'config']

    resolved = resolve_database_name(client, 'my_new_db')
    assert resolved == 'my_new_db'
