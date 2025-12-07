# Frontend Application

This is the frontend for the Telegram File Streaming application. It's a React application built with Vite.

## Architectural Overview

**Important:** This frontend application requires a specific backend API to function correctly. The `TG-FileStreamBot` (the Go application in the `/backend` directory) is **only a video streamer** and does **not** provide the necessary API for user data, video lists, or categories.

You need to run a separate application server that implements the API endpoints listed below. A comment in the code (`// Corrected endpoint to match the Python backend`) suggests this server is likely written in Python.

## Running Locally

1.  **Run the Go Streaming Service:**
    Follow the instructions in `/app/backend/README.md` to run the `TG-FileStreamBot`. By default, it runs on `http://localhost:8080`.

2.  **Run the (Missing) Application Backend:**
    You will need to create or obtain the application backend that provides the API endpoints below.

3.  **Run the Frontend:**
    *   Install dependencies: `npm install`
    *   If your application backend is running on a different URL, create a `.env` file and set the `VITE_API_BASE_URL` variable.
    *   Run the frontend: `npm run dev`

## Required API Endpoints

The application backend must implement the following API endpoints:

*   **`GET /api/profile`**
    *   Returns the user's profile information.
    *   Example Response: `{ "status": "Premium", "tokens": 100, "referrals": 5 }`

*   **`GET /api/categories`**
    *   Returns a list of available video categories.
    *   Example Response: `["Funny", "Dance", "Food", "Tech"]`

*   **`GET /api/feed/:category?page=<page>&limit=<limit>`**
    *   Returns a paginated list of videos for a given category.
    *   Example Response: `[{ "uuid": "video-uuid-1", "custom_caption": "A great video" }]`

*   **`GET /api/saved`**
    *   Returns a list of the user's saved/bookmarked videos.

*   **`POST /api/bookmark`**
    *   Toggles a video's bookmark status.
    *   Request Body: `{ "video_uuid": "video-uuid-1" }`
    *   Example Response: `{ "status": "added" }` or `{ "status": "removed" }`

*   **`GET /api/get-stream-url/:videoUuid`**
    *   This endpoint should proxy to the Go streaming service to get the actual video URL.
    *   Example Response: `{ "url": "http://localhost:8080/stream/..." }`
