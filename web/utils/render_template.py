import jinja2
import aiofiles
import os
import urllib.parse
import logging
import aiohttp
from web.utils.Template import rexbots_template
from web.utils.file_properties import get_file_ids
from web.utils.exceptions import InvalidHash
from web.utils import get_size

async def render_page(id: str, secure_hash: str, client, data_channel_id: int, bot_username: str, fqdn: str) -> str:
    # Step 1: Fetch Telegram file and metadata
    try:
        file_data = await get_file_ids(client, data_channel_id, int(id))
    except Exception as e:
        logging.error(f"Error fetching file info: {e}")
        raise

    # Step 2: Validate secure_hash
    if file_data.unique_id[:6] != secure_hash:
        logging.debug(f"link hash: {secure_hash} - {file_data.unique_id[:6]}")
        logging.debug(f"Invalid hash for message with - ID {id}")
        raise InvalidHash

    # Step 3: Construct file URL
    if not fqdn.endswith("/"):
        url_base = fqdn + "/"
    else:
        url_base = fqdn

    src = urllib.parse.urljoin(url_base, f"{id}?hash={secure_hash}")

    # Step 4: Determine file tag and get size
    tag = file_data.mime_type.split("/")[0].strip()

    file_size = get_size(file_data.file_size)

    if tag in ["video", "audio"]:
        template_file = os.path.join("web", "template", "watch.html")
    else:
        template_file = os.path.join("web", "template", "dl.html")
        # Optional: verify size from URL if needed, but we already have it from file_data

    # Step 5: Read the template file asynchronously
    try:
        async with aiofiles.open(template_file, mode='r') as f:
            content = await f.read()
        template = jinja2.Template(content)
    except Exception as e:
        logging.error(f"Error reading template: {e}")
        return "Template Error"

    # Step 6: Prepare file name safely
    file_name = file_data.file_name.replace("_", " ") if file_data.file_name else f"File_{id}.mkv"

    tg_link = f"https://t.me/{bot_username.replace('@', '')}?start=file_{id}"

    # Step 7: Render template with values
    return template.render(
        file_name=file_name,
        file_url=src,
        file_size=file_size,
        file_unique_id=file_data.unique_id,
        template_ne=rexbots_template.NAME,
        disclaimer=rexbots_template.DISCLAIMER,
        report_link=rexbots_template.REPORT_LINK,
        colours=rexbots_template.COLOURS,
        tg_button=tg_link,
    )
