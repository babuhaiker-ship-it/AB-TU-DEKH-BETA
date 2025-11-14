document.addEventListener('DOMContentLoaded', () => {
    const pages = {
        home: document.getElementById('home-page'),
        explore: document.getElementById('explore-page'),
        saved: document.getElementById('saved-page'),
        profile: document.getElementById('profile-page'),
    };
    const videoFeed = document.getElementById('video-feed');
    const bottomNav = document.getElementById('bottom-nav');
    const categoriesList = document.getElementById('categories-list');
    const savedVideosList = document.getElementById('saved-videos-list');
    const profileInfo = document.getElementById('profile-info');

     // Referral elements
    const referralLink = document.getElementById('referral-link');
    const referralCount = document.getElementById('referral-count');
    const copyReferralLinkButton = document.getElementById('copy-referral-link');

    // Buy token elements
    const buyTokenButton = document.getElementById('buy-token-button');

    // Refresh token elements
    const refreshTokenButton = document.getElementById('refresh-token-button');


    const API_BASE_URL = '/api';
    const initData = window.Telegram.WebApp.initData;

    let currentFeedPage = 1;
    let currentCategory = 'Action'; // Default category
    let isLoadingFeed = false; // Lock for infinite scroll

    // State to track which pages have had their initial content loaded
    const pageContentLoaded = {
        home: false,
        explore: false,
        saved: false,
        profile: false,
    };

    let appConfig = {}; // To store global configurations from the backend

    // To keep track of the currently playing video element
    let activeVideoElement = null;

    // --- API Helper ---
    async function fetchApi(endpoint, options = {}) {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            ...options,
            headers: {
                ...options.headers,
                'X-Telegram-Init-Data': initData,
            },
        });
        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                alert('Authentication failed. Please launch the app from Telegram.');
            }
            throw new Error(`API request failed with status ${response.status}`);
        }
        return response.json();
    }

    // --- Page Navigation ---
    function showPage(pageName) {
        Object.values(pages).forEach(page => page.style.display = 'none');
        pages[pageName].style.display = 'block';
        
        document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
        document.querySelector(`.nav-item[data-page="${pageName}"]`).classList.add('active');

        // Load data conditionally
        if (!pageContentLoaded[pageName]) {
            switch (pageName) {
                case 'home':
                    currentFeedPage = 1; // Reset page for new category/home view
                    loadFeed(currentCategory, currentFeedPage, false);
                    break;
                case 'explore':
                    loadCategories();
                    break;
                case 'saved':
                    loadSavedVideos();
                    break;
                case 'profile':
                    loadProfile();
                    break;
            }
            pageContentLoaded[pageName] = true;
        }
    }

    bottomNav.addEventListener('click', (e) => {
        const navItem = e.target.closest('.nav-item');
        if (navItem) {
            const pageName = navItem.dataset.page;
            // Before changing page, pause the current active video if it exists
            if (activeVideoElement) {
                activeVideoElement.pause();
                activeVideoElement = null;
            }
            showPage(pageName);
        }
    });

    // --- Content Loading ---
    async function loadFeed(category, page = 1, append = false) {
        if (isLoadingFeed) return; // Prevent multiple loads
        isLoadingFeed = true;

        if (!append) {
            videoFeed.innerHTML = ''; // Clear existing feed only if not appending
            videoFeed.scrollTop = 0; // Scroll to top for new category
        }

        try {
            const videos = await fetchApi(`/feed/${category}?page=${page}&limit=5`); // Fetch fewer videos for snap effect
            if (videos.length > 0) {
                videos.forEach(video => videoFeed.appendChild(createVideoItem(video)));
                currentFeedPage = page;
            } else if (page === 1) {
                videoFeed.innerHTML = '<p class="info-message">No videos found for this category. Try another!</p>';
            } else {
                console.log("No more videos to load for category:", category);
            }
        } catch (error) {
            console.error('Failed to load feed:', error);
            if (page === 1) {
                videoFeed.innerHTML = '<p class="error-message">Failed to load videos. Please try again later.</p>';
            }
        } finally {
            isLoadingFeed = false;
        }
    }

    // Infinite scroll listener for video feed
    videoFeed.addEventListener('scroll', () => {
        const { scrollTop, scrollHeight, clientHeight } = videoFeed;
        // Check if user is near the bottom (e.g., within 100px of the bottom)
        if (scrollTop + clientHeight >= scrollHeight - 100 && !isLoadingFeed) {
            console.log("Loading more videos...");
            loadFeed(currentCategory, currentFeedPage + 1, true); // Load next page and append
        }
    });


    async function loadCategories() {
        categoriesList.innerHTML = '';
        try {
            const categories = await fetchApi('/categories');
            if (categories.length > 0) {
                categories.forEach(category => {
                    const categoryItem = document.createElement('div');
                    categoryItem.classList.add('category-item'); // Add a class for styling
                    categoryItem.textContent = category;
                    categoryItem.addEventListener('click', () => {
                        currentCategory = category;
                        pageContentLoaded.home = false; // Force reload home page for new category
                        showPage('home');
                    });
                    categoriesList.appendChild(categoryItem);
                });
            } else {
                categoriesList.innerHTML = '<p class="info-message">No categories available.</p>';
            }
        } catch (error) {
            console.error('Failed to load categories:', error);
            categoriesList.innerHTML = '<p class="error-message">Failed to load categories. Please try again later.</p>';
        }
    }

    async function loadSavedVideos() {
        savedVideosList.innerHTML = '';
        try {
            const videos = await fetchApi('/saved');
            if (videos.length > 0) {
                videos.forEach(video => savedVideosList.appendChild(createVideoItem(video)));
            } else {
                savedVideosList.innerHTML = '<p class="info-message">You haven't saved any videos yet. Bookmark your favorites!</p>';
            }
        } catch (error) {
            console.error('Failed to load saved videos:', error);
            savedVideosList.innerHTML = '<p class="error-message">Failed to load saved videos. Please try again later.</p>';
        }
    }

    async function loadProfile() {
        profileInfo.innerHTML = '';
        try {
            const profile = await fetchApi('/profile');
            profileInfo.innerHTML = `
                <p>Status: ${profile.status}</p>
                <p>Tokens: ${profile.tokens}</p>
                <p>Referrals: ${profile.referrals}</p>
            `;

            // Update referral info
            referralLink.textContent = profile.referral_link; // Use referral_link from API
            referralCount.textContent = profile.referrals; 

        } catch (error) {
            console.error('Failed to load profile:', error);
            profileInfo.innerHTML = '<p class="error-message">Failed to load profile. Please try again later.</p>';
        }
    }
    
    function createVideoItem(video) {
        const videoItem = document.createElement('div');
        videoItem.classList.add('video-item');
        videoItem.dataset.videoId = video.uuid;

        const videoElement = document.createElement('video');
        videoElement.preload = 'metadata';
        videoElement.loop = true; // TikTok videos loop
        videoElement.playsInline = true; // Important for iOS to play inline

        const videoOverlay = document.createElement('div');
        videoOverlay.classList.add('video-overlay');

        const caption = document.createElement('div');
        caption.classList.add('video-caption');
        caption.textContent = video.custom_caption;

        const actions = document.createElement('div');
        actions.classList.add('video-actions');
        
        const bookmarkIcon = document.createElement('span');
        bookmarkIcon.classList.add('action-icon');
        bookmarkIcon.innerHTML = '&#x1F516;'; // Bookmark icon
        bookmarkIcon.addEventListener('click', () => toggleBookmark(video.uuid, bookmarkIcon));

        // Share button
        const shareIcon = document.createElement('span');
        shareIcon.classList.add('action-icon');
        shareIcon.innerHTML = '&#x1F504;'; // Share icon
        shareIcon.addEventListener('click', () => shareVideo(video.uuid));

        actions.appendChild(bookmarkIcon);
        actions.appendChild(shareIcon); // Add share icon
        videoOverlay.appendChild(caption);
        videoOverlay.appendChild(actions);

        videoItem.appendChild(videoElement);
        videoItem.appendChild(videoOverlay);

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.target === videoItem) { // Ensure it's the right entry
                    if (entry.isIntersecting) {
                        // Pause all other videos
                        document.querySelectorAll('#video-feed video').forEach(vid => {
                            if (vid !== videoElement && !vid.paused) {
                                vid.pause();
                            }
                        });
                        playVideo(videoElement, video.uuid);
                        activeVideoElement = videoElement;
                    } else {
                        videoElement.pause();
                        if (activeVideoElement === videoElement) {
                            activeVideoElement = null;
                        }
                    }
                }
            });
        }, { threshold: 0.8 }); // Video plays when 80% visible

        observer.observe(videoItem);

        return videoItem;
    }

    async function playVideo(videoElement, videoId) {
        try {
            const data = await fetchApi(`/get-stream-url/${videoId}`);
            videoElement.src = data.url;
            await videoElement.play();
        } catch (error) {
            console.error('Failed to get video stream URL:', error);
            // Optionally, show a message on the video item
            videoElement.insertAdjacentHTML('afterend', '<p class="error-message">Video unavailable</p>');
        }
    }

    async function toggleBookmark(videoId, iconElement) {
        try {
            const response = await fetchApi('/bookmark', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ "video_uuid": videoId }),
            });

            if (response.status === 'added') {
                iconElement.innerHTML = '&#x1F517;'; // Filled bookmark icon
                alert('Video bookmarked!');
            } else if (response.status === 'removed') {
                iconElement.innerHTML = '&#x1F516;'; // Empty bookmark icon
                alert('Bookmark removed!');
            }
        } catch (error) {
            console.error('Failed to toggle bookmark:', error);
            alert('Failed to toggle bookmark. ' + (error.detail || 'Please try again.'));
        }
    }

    async function shareVideo(videoId) {
        try {
            const shareUrl = `https://t.me/${appConfig.bot_username}?start=video_${videoId}`;
            await navigator.clipboard.writeText(shareUrl);
            alert('Video share link copied to clipboard! Share it in Telegram to earn tokens.');
        } catch (error) {
            console.error('Failed to copy share link:', error);
            alert('Failed to copy share link. Please try again.');
        }
    }

     // --- Referral Link Copy ---
    copyReferralLinkButton.addEventListener('click', () => {
        const link = referralLink.textContent;
        navigator.clipboard.writeText(link).then(() => {
            alert('Referral link copied!');
        }).catch(err => {
            console.error('Failed to copy link: ', err);
            alert('Failed to copy referral link.');
        });
    });

    // --- Buy Token Action ---
    buyTokenButton.addEventListener('click', () => {
        if (appConfig.buy_bot_url) {
            window.open(appConfig.buy_bot_url, '_blank');
        } else {
            alert('Buy token URL is not configured. Please try again later.');
        }
    });

     // --- Refresh Token Action ---
    refreshTokenButton.addEventListener('click', () => {
        if (appConfig.bot_username) {
            window.open(`https://t.me/${appConfig.bot_username}?start=refresh_request`, '_blank');
        } else {
            alert('Bot username is not configured. Please try again later.');
        }
    });

    // --- Initial Load ---
    async function initializeApp() {
        try {
            appConfig = await fetchApi('/config');
            // Set initial category if available, otherwise default to 'Action'
            currentCategory = appConfig.default_category || 'Action'; 
            console.log("App Config loaded:", appConfig);
        } catch (error) {
            console.error('Failed to load app configuration:', error);
            alert('Failed to load app configuration. Some features may not work.');
        }

        showPage('home');
        // Initial load for home feed is handled by showPage
    }

    initializeApp();
});
