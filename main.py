
import asyncio
import logging
from bot import (
    app,
    get_session_string,
    set_session_string,
    load_admins_from_db,
    load_data_channel_id,
    load_force_sub_channels,
    health_check,
    cleanup_expired_data,
    verify_and_cleanup_media,
    cleanup_expired_menus,
    create_tracked_task,
    active_tasks,
)

logger = logging.getLogger(__name__)

async def main():
    """
    Main function to start the bot and background tasks.
    """
    logger.info("Starting the bot...")

    # Start the Pyrogram client
    await app.start()
    logger.info("Pyrogram client started.")

    # If this is the first run, save the session string
    SESSION_STRING = get_session_string()
    if not SESSION_STRING:
        logger.info("Saving session string to DB for future runs...")
        new_session_string = await app.export_session_string()
        set_session_string(new_session_string)

    # Load admins and run background tasks
    await load_admins_from_db()
    await load_data_channel_id()
    await load_force_sub_channels()
    await health_check()
    create_tracked_task(cleanup_expired_data())
    create_tracked_task(verify_and_cleanup_media())
    create_tracked_task(cleanup_expired_menus())
    logger.info("Background tasks initiated. Bot is now fully operational.")

    # Keep the bot running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Bot stopped due to a critical error: {e}", exc_info=True)
    finally:
        # Graceful shutdown
        if app.is_initialized:
            app.stop()
        for task in active_tasks:
            task.cancel()
