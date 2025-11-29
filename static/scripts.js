document.addEventListener('DOMContentLoaded', () => {
    const categoryContainer = document.getElementById('category-container');
    const videoFeed = document.getElementById('video-feed');
    let currentCategory = null;
    const tg = window.Telegram.WebApp;

    // Initialize the Telegram Web App
    tg.ready();

    const headers = {
        'X-Telegram-Init-Data': tg.initData
    };

    // Fetch categories and populate the category container
    fetch('/api/categories', { headers })
        .then(response => response.json())
        .then(categories => {
            categories.forEach(category => {
                const button = document.createElement('button');
                button.textContent = category;
                button.classList.add('category-button');
                button.addEventListener('click', () => {
                    currentCategory = category;
                    loadVideos(category);
                });
                categoryContainer.appendChild(button);
            });
            // Load the first category by default
            if (categories.length > 0) {
                currentCategory = categories[0];
                loadVideos(currentCategory);
            }
        });

    // Function to load videos for a given category
    function loadVideos(category) {
        videoFeed.innerHTML = '<div class="loading">Loading...</div>';
        fetch(`/api/feed/${category}`, { headers })
            .then(response => response.json())
            .then(videos => {
                videoFeed.innerHTML = '';
                videos.forEach(video => {
                    const videoContainer = document.createElement('div');
                    videoContainer.classList.add('video-container');

                    const videoElement = document.createElement('video');
                    videoElement.src = `/stream/${video.uuid}`;
                    videoElement.controls = true;
                    videoElement.autoplay = true;
                    videoElement.loop = true;
                    videoElement.muted = true; // Autoplay requires the video to be muted

                    const captionElement = document.createElement('div');
                    captionElement.classList.add('video-caption');
                    captionElement.textContent = video.custom_caption || '';

                    videoContainer.appendChild(videoElement);
                    videoContainer.appendChild(captionElement);
                    videoFeed.appendChild(videoContainer);
                });
            });
    }
});
