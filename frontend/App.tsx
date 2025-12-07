import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useTelegramWebApp } from './hooks/useTelegramWebApp';
import { fetchProfile, fetchSavedVideos, toggleBookmark as apiToggleBookmark } from './services/apiService';
import type { ProfileData, Screen, Video } from './types';
import VideoFeed from './components/VideoFeed';
import CategoryList from './components/CategoryList';
import ProfileView from './components/ProfileView';
import SavedVideos from './components/SavedVideos';
import Navbar from './components/Navbar';
import Spinner from './components/Spinner';

const App: React.FC = () => {
  const { webApp, initData } = useTelegramWebApp();
  const [activeScreen, setActiveScreen] = useState<Screen>('feed');
  const [selectedCategory, setSelectedCategory] = useState<string>('General');
  const [profileData, setProfileData] = useState<ProfileData | null>(null);
  const [savedVideos, setSavedVideos] = useState<Video[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const getAuthHeaders = useCallback(() => {
    return { 'X-Telegram-Init-Data': initData || '' };
  }, [initData]);

  const loadInitialData = useCallback(async () => {
    if (!initData) return;
    setIsLoading(true);
    setError(null);
    try {
      const authHeaders = getAuthHeaders();
      const [profile, saved] = await Promise.all([
        fetchProfile(authHeaders),
        fetchSavedVideos(authHeaders),
      ]);
      setProfileData(profile);
      setSavedVideos(saved);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unknown error occurred.';
      console.error('Failed to load initial data:', errorMessage);
      setError(`Failed to load app data. Please try again later. Error: ${errorMessage}`);
      webApp?.showAlert('Failed to load app data.');
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, webApp, initData]);

  useEffect(() => {
    if (initData && initData.length > 0) {
      loadInitialData();
    } else {
        setIsLoading(false);
        setError("Could not verify Telegram user. Please launch this app through the bot.");
    }
  }, [initData, loadInitialData]);

  const handleSelectCategory = (category: string) => {
    setSelectedCategory(category);
    setActiveScreen('feed');
  };

  const toggleBookmark = useCallback(async (video: Video) => {
    const isCurrentlySaved = savedVideos.some(v => v.uuid === video.uuid);

    // Optimistic UI update for a responsive feel
    setSavedVideos(prev =>
      isCurrentlySaved
      ? prev.filter(v => v.uuid !== video.uuid)
      : [...prev, video]
    );

    try {
      const result = await apiToggleBookmark(video.uuid, getAuthHeaders());
      webApp?.HapticFeedback.notificationOccurred(result.status === 'added' ? 'success' : 'warning');

      // If API status mismatches our optimistic update, something is wrong. Re-fetch to be safe.
      if ((result.status === 'added' && isCurrentlySaved) || (result.status === 'removed' && !isCurrentlySaved)) {
        throw new Error("Bookmark status mismatch with optimistic update");
      }
    } catch (err) {
      console.error('Failed to toggle bookmark:', err);
      webApp?.showAlert('Failed to update bookmark.');
      // Revert optimistic update on failure
      setSavedVideos(prev =>
        isCurrentlySaved
        ? [...prev, video]
        : prev.filter(v => v.uuid !== video.uuid)
      );
    }
  }, [savedVideos, getAuthHeaders, webApp]);

  const handleRefreshProfile = useCallback(() => {
    if (!initData) return;
    fetchProfile(getAuthHeaders()).then(setProfileData).catch(console.error);
  }, [getAuthHeaders, initData]);

  const handleRefreshSaved = useCallback(() => {
    if (!initData) return;
    fetchSavedVideos(getAuthHeaders()).then(setSavedVideos).catch(console.error);
  }, [getAuthHeaders, initData]);

  const savedVideoUuids = useMemo(() => savedVideos.map(v => v.uuid), [savedVideos]);

  const renderScreen = () => {
    if (isLoading) {
      return <div className="flex items-center justify-center h-full"><Spinner /></div>;
    }
    if (error) {
      return <div className="flex items-center justify-center h-full text-red-500 p-4 text-center">{error}</div>;
    }

    switch (activeScreen) {
      case 'feed':
        return <VideoFeed
                  key={selectedCategory}
                  category={selectedCategory}
                  getAuthHeaders={getAuthHeaders}
                  toggleBookmark={toggleBookmark}
                  savedVideoUuids={savedVideoUuids}
                />;
      case 'categories':
        return <CategoryList onSelectCategory={handleSelectCategory} getAuthHeaders={getAuthHeaders} />;
      case 'saved':
        return <SavedVideos
                  savedVideos={savedVideos}
                  getAuthHeaders={getAuthHeaders}
                  toggleBookmark={toggleBookmark}
                />;
      case 'profile':
        return <ProfileView profileData={profileData} isLoading={!profileData} />;
      default:
        return <VideoFeed
                  category={selectedCategory}
                  getAuthHeaders={getAuthHeaders}
                  toggleBookmark={toggleBookmark}
                  savedVideoUuids={savedVideoUuids}
               />;
    }
  };

  return (
    <div className="h-screen w-screen bg-black text-white flex flex-col font-sans overflow-hidden">
      <main className="flex-1 relative">
        {renderScreen()}
      </main>
      <Navbar
        activeScreen={activeScreen}
        setActiveScreen={setActiveScreen}
        onProfileClick={handleRefreshProfile}
        onSavedClick={handleRefreshSaved}
      />
    </div>
  );
};

export default App;
