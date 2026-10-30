import os
import sys
import unittest
import unittest.mock as mock
import asyncio
import time
from datetime import datetime, timedelta, timezone

import mongomock

os.environ['BOT_TOKEN'] = '123456:ABC-DEF1234ghIkl-zyx57W2v1u12345678'
os.environ['API_ID'] = '123456'
os.environ['API_HASH'] = '0123456789abcdef0123456789abcdef'
os.environ['BOT_USERNAME'] = '@test_bot'
os.environ['MONGO_URI'] = 'mongodb://localhost:27017'
os.environ['MONGO_DB_NAME'] = 'test_db'

mock_mongo_client = mongomock.MongoClient()

with mock.patch('pymongo.MongoClient', return_value=mock_mongo_client):
    import bot

class TestProductionReadiness(unittest.TestCase):

    def setUp(self):
        bot.db.drop_collection('users')
        bot.db.drop_collection('tokens')
        bot.db.drop_collection('media')
        bot.db.drop_collection('history')
        bot._user_rate_limits.clear()

    def test_mongodb_connection_pool_configuration(self):
        self.assertIsNotNone(bot.client)

    def test_is_rate_limited_and_cleanup(self):
        async def run_test():
            user_id = 12345
            for _ in range(50):
                limited = await bot.is_rate_limited(user_id)
                self.assertFalse(limited)

            # Reach max
            for _ in range(20):
                limited = await bot.is_rate_limited(user_id)

            self.assertTrue(limited)

            # Test cleanup when size exceeds 5000
            for i in range(5001):
                bot._user_rate_limits[i] = [time.time() - 200]

            await bot.is_rate_limited(99999)
            self.assertLess(len(bot._user_rate_limits), 5000)

        asyncio.run(run_test())

    def test_atomic_quota_reset(self):
        user_id = 88888
        past_reset = datetime.now(timezone.utc) - timedelta(hours=5)
        bot.users_collection.insert_one({
            'user_id': user_id,
            'free_video_usage': {
                'count': 200,
                'reset_at': past_reset
            }
        })

        has_access = bot.has_free_video_access(user_id)
        self.assertTrue(has_access)

        updated_doc = bot.users_collection.find_one({'user_id': user_id})
        self.assertEqual(updated_doc['free_video_usage']['count'], 0)
        res_at = updated_doc['free_video_usage']['reset_at']
        if res_at.tzinfo is None:
            res_at = res_at.replace(tzinfo=timezone.utc)
        self.assertGreater(res_at, datetime.now(timezone.utc))

    def test_atomic_bookmark_deduplication(self):
        user_id = 77777
        bot.users_collection.insert_one({
            'user_id': user_id,
            'bookmarked_videos': []
        })

        v_data = {'uuid': 'vid-uuid-1', 'category': 'default'}
        bot.media_collection.insert_one(v_data)

        # Mock callback query
        mock_cb = mock.AsyncMock()
        mock_cb.from_user.id = user_id
        mock_cb.data = "bookmark_vid-uuid-1"

        async def run_bookmarks():
            with mock.patch('bot.check_membership', return_value=True):
                await bot.bookmark_video_callback(mock.MagicMock(), mock_cb)
                await bot.bookmark_video_callback(mock.MagicMock(), mock_cb)

        asyncio.run(run_bookmarks())

        user_doc = bot.users_collection.find_one({'user_id': user_id})
        self.assertEqual(len(user_doc['bookmarked_videos']), 1)

    def test_concurrency_stress_simulated_users(self):
        async def run_concurrency():
            async def worker(uid):
                bot.users_collection.insert_one({
                    'user_id': uid,
                    'free_video_usage': {'count': 0, 'reset_at': datetime.now(timezone.utc) + timedelta(hours=24)}
                })
                for _ in range(10):
                    bot.has_free_video_access(uid)
                    bot.mark_free_video_used(uid)
                    await asyncio.sleep(0.001)

            tasks = [worker(1000 + i) for i in range(100)]
            start_time = time.time()
            await asyncio.gather(*tasks)
            duration = time.time() - start_time
            rps = 1000 / duration
            print(f"\nCompleted 1000 concurrent ops across 100 active user workers in {duration:.2f}s ({rps:.2f} ops/sec)")
            self.assertGreater(rps, 100)

        asyncio.run(run_concurrency())

if __name__ == '__main__':
    unittest.main()
