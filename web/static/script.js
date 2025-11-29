document.addEventListener('DOMContentLoaded', () => {
    const videoContainer = document.getElementById('video-container');
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    if (!token) {
        videoContainer.innerHTML = '<p style="color: white; text-align: center;">Access token is missing. Please use the link provided by the bot.</p>';
        return;
    }

    // Fetch the list of saved video UUIDs from the backend
    fetch(`/api/videos?token=${token}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch videos. Your session may have expired.');
            }
            return response.json();
        })
        .then(videos => {
            if (videos.length === 0) {
                videoContainer.innerHTML = '<p style="color: white; text-align: center;">You have no saved videos.</p>';
                return;
            }

            // Create and append video elements to the container
            videos.forEach((video, index) => {
                const videoWrapper = document.createElement('div');
                videoWrapper.className = 'video-wrapper';

                const videoElement = document.createElement('video');
                videoElement.src = `/stream/${video.uuid}?token=${token}`;
                videoElement.controls = true;
                videoElement.preload = 'metadata';
                videoElement.loop = true;

                // Mute the videos by default to allow autoplay in most browsers
                videoElement.muted = true;

                if (index === 0) {
                    videoElement.autoplay = true;
                }

                videoWrapper.appendChild(videoElement);
                videoContainer.appendChild(videoWrapper);
            });

            setupIntersectionObserver();
        })
        .catch(error => {
            videoContainer.innerHTML = `<p style="color: red; text-align: center;">Error: ${error.message}</p>`;
        });

    function setupIntersectionObserver() {
        const options = {
            root: videoContainer,
            rootMargin: '0px',
            threshold: 0.8 // Trigger when 80% of the video is visible
        };

        const callback = (entries, observer) => {
            entries.forEach(entry => {
                const video = entry.target.querySelector('video');
                if (entry.isIntersecting) {
                    // Play the video when it comes into view
                    video.play().catch(e => console.error("Autoplay was prevented:", e));
                } else {
                    // Pause the video when it goes out of view
                    video.pause();
                }
            });
        };

        const observer = new IntersectionObserver(callback, options);
        document.querySelectorAll('.video-wrapper').forEach(wrapper => {
            observer.observe(wrapper);
        });
    }
});
