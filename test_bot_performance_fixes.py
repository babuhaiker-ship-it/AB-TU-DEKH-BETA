import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import asyncio

# Set dummy env vars for bot initialization before importing bot
os.environ['BOT_TOKEN'] = '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
os.environ['API_ID'] = '123456'
os.environ['API_HASH'] = 'abcdef1234567890abcdef1234567890'
os.environ['BOT_USERNAME'] = 'test_bot'
os.environ['MONGO_URI'] = 'mongodb://localhost:27017'
os.environ['MONGO_DB_NAME'] = 'test_db'

# Patch MongoClient before bot imports DB collections
with patch('pymongo.MongoClient'):
    import bot

class TestBotPerformanceFixes(unittest.TestCase):

    def setUp(self):
        bot.invalidate_categories_cache()

    @patch('bot.categories_collection')
    def test_get_categories_caching(self, mock_cat_coll):
        mock_cat_coll.find.return_value = [{'name': 'Action'}, {'name': 'Comedy'}]

        # First call fetches from db
        cats1 = bot.get_categories(for_admin_use=True)
        self.assertEqual(cats1, ['Action', 'Comedy'])
        self.assertEqual(mock_cat_coll.find.call_count, 1)

        # Second call should use cache
        cats2 = bot.get_categories(for_admin_use=True)
        self.assertEqual(cats2, ['Action', 'Comedy'])
        self.assertEqual(mock_cat_coll.find.call_count, 1)

        # Invalidate cache and call again
        bot.invalidate_categories_cache()
        cats3 = bot.get_categories(for_admin_use=True)
        self.assertEqual(cats3, ['Action', 'Comedy'])
        self.assertEqual(mock_cat_coll.find.call_count, 2)

    @patch('bot.media_collection')
    def test_get_video_and_position_optimized(self, mock_media_coll):
        test_uuid = 'test-uuid-123'
        category = 'Action'
        dummy_video = {'uuid': test_uuid, 'category': category, 'sequence_number': 5, 'banned': False}

        mock_media_coll.find_one.return_value = dummy_video
        mock_media_coll.count_documents.side_effect = [10, 5] # Total count: 10, Position: 5

        video, pos, total = bot.get_video_and_position(test_uuid, category, is_saved=False)

        self.assertEqual(video, dummy_video)
        self.assertEqual(pos, 5)
        self.assertEqual(total, 10)
        self.assertEqual(mock_media_coll.count_documents.call_count, 2)

    @patch('bot.tokens_collection')
    def test_is_rate_limited_async(self, mock_tokens_coll):
        mock_tokens_coll.find_one.return_value = {'rate_limits': [{'timestamp': 1}, {'timestamp': 2}]}

        # Should execute using asyncio.to_thread without blocking
        result = asyncio.run(bot.is_rate_limited(99999))
        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
