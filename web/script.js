
window.Telegram.WebApp.ready();

const feed = document.getElementById('feed');
const categorySelector = document.getElementById('category-selector');
const categoriesContainer = document.getElementById('categories');
const loading = document.getElementById('loading');

let currentCategory = null;
let videos = [];
let currentIndex = 0;
let isLoading = false;

function showLoading() {
    loading.style.display = 'block';
}

function hideLoading() {
    loading.style.display = 'none';
}

function showError(message) {
    const errorDisplay = document.getElementById('error-display');
    if (errorDisplay) {
        errorDisplay.innerText = message;
        errorDisplay.style.display = 'block';
    }
    // Hide category selector and loading indicators
    if (categorySelector) categorySelector.style.display = 'none';
    if (loading) loading.style.display = 'none';
}

async function fetchWithAuth(url) {
    if (!window.Telegram.WebApp.initData) {
        console.error("Authentication data not available. Make sure you are running the app inside Telegram.");
        showError("Authentication failed. Please open this app through your Telegram client.");
        throw new Error("Missing Telegram Init Data");
    }

    const headers = {
        'X-Telegram-Init-Data': window.Telegram.WebApp.initData
    };
    const response = await fetch(url, { headers });
    if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to fetch data');
    }
    return response.json();
}

async function getStreamUrl(videoUuid) {
    try {
        const data = await fetchWithAuth(`/api/get-stream-url/${videoUuid}`);
        return data.url;
    } catch (error) {
        console.error('Error getting stream URL:', error);
        window.Telegram.WebApp.showAlert('Could not load video. Please try again later.');
        return null;
    }
}

async function loadVideo(index) {
    if (index < 0 || index >= videos.length) return;

    const videoData = videos[index];
    const existingContainer = document.getElementById(`video-${videoData.uuid}`);
    if (existingContainer && existingContainer.querySelector('video')) {
        return;
    }

    const streamUrl = await getStreamUrl(videoData.uuid);
    if (!streamUrl) return;

    const container = existingContainer || document.createElement('div');
    container.className = 'video-container';
    container.id = `video-${videoData.uuid}`;

    const videoElement = document.createElement('video');
    videoElement.src = streamUrl;
    videoElement.setAttribute('playsinline', '');
    videoElement.setAttribute('loop', '');

    container.innerHTML = '';
    container.appendChild(videoElement);

    if (!existingContainer) {
        feed.appendChild(container);
    }
}

function playCurrentVideo() {
    const containers = document.querySelectorAll('.video-container');
    containers.forEach((container, index) => {
        const video = container.querySelector('video');
        if (index === currentIndex) {
            video?.play().catch(e => console.error("Play failed:", e));
        } else {
            video?.pause();
        }
    });
}

async function loadInitialVideos() {
    showLoading();
    feed.innerHTML = '';
    for (let i = 0; i < Math.min(3, videos.length); i++) {
        await loadVideo(i);
    }
    currentIndex = 0;
    playCurrentVideo();
    hideLoading();
}

async function fetchVideos(category) {
    if (isLoading) return;
    isLoading = true;
    showLoading();
    try {
        const videoData = await fetchWithAuth(`/api/feed/${category}`);
        videos = videoData;
        await loadInitialVideos();
        categorySelector.style.display = 'none';
    } catch (error) {
        console.error('Error fetching videos:', error);
        window.Telegram.WebApp.showAlert('Failed to load videos for this category.');
    } finally {
        isLoading = false;
        hideLoading();
    }
}

async function fetchCategories() {
    showLoading();
    try {
        const categories = await fetchWithAuth('/api/categories');
        categoriesContainer.innerHTML = '';
        categories.forEach(category => {
            const button = document.createElement('button');
            button.innerText = category;
            button.onclick = () => {
                currentCategory = category;
                fetchVideos(category);
            };
            categoriesContainer.appendChild(button);
        });
    } catch (error) {
        console.error('Error fetching categories:', error);
        window.Telegram.WebApp.showAlert('Could not load categories. Please restart the app.');
    } finally {
        hideLoading();
    }
}

feed.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = feed;
    const newIndex = Math.round(scrollTop / clientHeight);

    if (newIndex !== currentIndex) {
        currentIndex = newIndex;
        playCurrentVideo();

        // Preload next and previous videos
        loadVideo(currentIndex + 1);
        loadVideo(currentIndex - 1);
    }
});


document.addEventListener('DOMContentLoaded', () => {
    window.Telegram.WebApp.expand();
    fetchCategories();
});
