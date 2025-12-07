# TG-FileStreamBot (Go version)

This is the backend server for the file streaming application. It's written in Go and uses Telegram as a CDN.

## Running Locally

**Prerequisites:** Go (version 1.21 or later)

1.  **Install Dependencies:**
    Open your terminal in this directory and run:
    ```bash
    go get .
    ```

2.  **Create an Environment File:**
    Copy the sample environment file:
    ```bash
    cp fsb.sample.env .env
    ```

3.  **Configure Environment Variables:**
    Open the `.env` file and fill in the required variables:
    *   `API_ID`: Your Telegram API ID (from my.telegram.org)
    *   `API_HASH`: Your Telegram API Hash (from my.telegram.org)
    *   `BOT_TOKEN`: Your Telegram bot token (from @BotFather)
    *   `LOG_CHANNEL`: The ID of a private Telegram channel (with the bot as an admin) to store the files.

4.  **Run the Server:**
    ```bash
    go run cmd/fsb/main.go
    ```
    The server will start on port 8080 by default.
