
import type { ProfileData, Video } from '../types';

// --- MOCK DATA FOR LOCAL DEVELOPMENT ---

const mockVideos: Video[] = [
    { uuid: 'mock-vid-1', custom_caption: 'A cat playing a piano', category: 'Funny' },
    { uuid: 'mock-vid-2', custom_caption: 'Amazing street dance performance', category: 'Dance' },
    { uuid: 'mock-vid-3', custom_caption: 'How to cook a perfect steak', category: 'Food' },
    { uuid: 'mock-vid-4', custom_caption: 'Cool generative art with code', category: 'Art' },
    { uuid: 'mock-vid-5', custom_caption: 'Exploring the latest in AI', category: 'Tech' },
    { uuid: 'mock-vid-6', custom_caption: 'This is a general video', category: 'General' },
    { uuid: 'mock-vid-7', custom_caption: 'Another funny one', category: 'Funny' },
    { uuid: 'mock-vid-8', custom_caption: 'Epic gaming moments', category: 'Gaming' },
    { uuid: 'mock-vid-9', custom_caption: 'New hit song', category: 'Music' },
    { uuid: 'mock-vid-10', custom_caption: 'One more for the road', category: 'General' },
];

let mockSavedUuids = ['mock-vid-2', 'mock-vid-4'];

const mockStreamableUrls: Record<string, string> = {
    'mock-vid-1': 'https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
    'mock-vid-2': 'https://storage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4',
    'mock-vid-3': 'https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
    'mock-vid-4': 'https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4',
    'mock-vid-5': 'https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4',
    'mock-vid-6': 'https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4',
    'mock-vid-7': 'https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerMeltdowns.mp4',
    'mock-vid-8': 'https://storage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4',
    'mock-vid-9': 'https://storage.googleapis.com/gtv-videos-bucket/sample/SubaruOutbackOnStreetAndDirt.mp4',
    'mock-vid-10': 'https://storage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4',
};

// Check if the app is running in mock mode (i.e., outside Telegram)
const isMockMode = (headers: HeadersInit): boolean => {
    const initData = (headers as Record<string, string>)['X-Telegram-Init-Data'];
    return initData === 'mock_init_data_string_for_development';
};

// --- API IMPLEMENTATION ---

const getApiBaseUrl = (): string => {
  return import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";
};

async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${getApiBaseUrl()}${endpoint}`;
  const response = await fetch(url, options);

  if (!response.ok) {
    const errorBody = await response.text();
    let errorDetail = 'Unknown error';
    try {
        const errorJson = JSON.parse(errorBody);
        errorDetail = errorJson.detail || 'Unknown error';
    } catch(e) {
        errorDetail = errorBody.substring(0, 100);
    }
    throw new Error(`API error: ${response.status} ${response.statusText} - ${errorDetail}`);
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json();
}

export const fetchProfile = (headers: HeadersInit): Promise<ProfileData> => {
  if (isMockMode(headers)) {
    console.log("MOCK MODE: Fetching profile");
    return new Promise(resolve => setTimeout(() => resolve({
      status: 'Premium',
      tokens: 1337,
      referrals: 42,
    }), 500));
  }
  return apiFetch<ProfileData>('/api/profile', { headers });
};

export const fetchCategories = (headers: HeadersInit): Promise<string[]> => {
  if (isMockMode(headers)) {
    console.log("MOCK MODE: Fetching categories");
    const categories = [...new Set(mockVideos.map(v => v.category))];
    return new Promise(resolve => setTimeout(() => resolve(categories), 500));
  }
  return apiFetch<string[]>('/api/categories', { headers });
};

export const fetchFeed = async (category: string, page: number, limit: number, headers: HeadersInit): Promise<Video[]> => {
  if (isMockMode(headers)) {
      console.log(`MOCK MODE: Fetching feed for category "${category}", page ${page}`);
      return new Promise(resolve => setTimeout(() => {
          if (page > 2) { // Simulate end of content
              resolve([]);
              return;
          }
          const filteredVideos = mockVideos.filter(v => category === 'General' ? true : v.category === category);
          const start = (page - 1) * limit;
          const end = start + limit;
          resolve(filteredVideos.slice(start, end));
      }, 500));
  }
  const endpoint = `/api/feed/${encodeURIComponent(category)}?page=${page}&limit=${limit}`;
  // The backend API for feed doesn't include the category in the response items, so we add it here for consistency.
  const videosWithoutCategory = await apiFetch<Omit<Video, 'category'>[]>(endpoint, { headers });
  return videosWithoutCategory.map(video => ({ ...video, category }));
};

export const fetchStreamableUrl = async (videoUuid: string, headers: HeadersInit): Promise<string> => {
    if (isMockMode(headers)) {
        console.log(`MOCK MODE: Fetching streamable URL for ${videoUuid}`);
        return new Promise(resolve => setTimeout(() => {
            resolve(mockStreamableUrls[videoUuid] || mockStreamableUrls['mock-vid-1']);
        }, 200));
    }
    // Corrected endpoint to match the Python backend
    const response = await apiFetch<{ url: string }>(`/api/get-stream-url/${videoUuid}`, { headers });
    return response.url;
};

export const fetchSavedVideos = async (headers: HeadersInit): Promise<Video[]> => {
  if (isMockMode(headers)) {
    console.log("MOCK MODE: Fetching saved videos");
    const saved = mockVideos.filter(v => mockSavedUuids.includes(v.uuid));
    return new Promise(resolve => setTimeout(() => resolve(saved), 500));
  }
  // The /api/saved endpoint now returns an array of full Video objects.
  return apiFetch<Video[]>('/api/saved', { headers });
};

export const toggleBookmark = (videoUuid: string, headers: HeadersInit): Promise<{ status: 'added' | 'removed' }> => {
  if (isMockMode(headers)) {
      console.log(`MOCK MODE: Toggling bookmark for ${videoUuid}`);
      return new Promise(resolve => setTimeout(() => {
          const index = mockSavedUuids.indexOf(videoUuid);
          if (index > -1) {
              mockSavedUuids.splice(index, 1);
              console.log("MOCK MODE: Saved UUIDs:", mockSavedUuids);
              resolve({ status: 'removed' });
          } else {
              mockSavedUuids.push(videoUuid);
              console.log("MOCK MODE: Saved UUIDs:", mockSavedUuids);
              resolve({ status: 'added' });
          }
      }, 300));
  }
  return apiFetch<{ status: 'added' | 'removed' }>('/api/bookmark', {
    method: 'POST',
    headers: {
      ...headers,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ video_uuid: videoUuid }),
  });
};

export const fetchVideoDetails = async (uuid: string, headers: HeadersInit): Promise<Video | null> => {
    if (isMockMode(headers)) {
        console.log(`MOCK MODE: Fetching details for ${uuid}`);
        return new Promise(resolve => setTimeout(() => {
            const video = mockVideos.find(v => v.uuid === uuid) || null;
            resolve(video);
        }, 300));
    }
    try {
        return await apiFetch<Video>(`/api/video/${uuid}`, { headers });
    } catch (error) {
        console.error(`Error fetching details for video ${uuid}:`, error);
        return null;
    }
};
