import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchFeed } from '../services/apiService';
import type { Video } from '../types';
import VideoCard from './VideoCard';
import Spinner from './Spinner';
import { useSwipeable } from 'react-swipeable';

const VIDEOS_PER_PAGE = 5;

interface VideoFeedProps {
  category: string;
  getAuthHeaders: () => HeadersInit;
  // FIX: Changed type from `(videoUuid: string)` to `(video: Video)` to match parent and child component definitions.
  toggleBookmark: (video: Video) => Promise<void>;
  savedVideoUuids: string[];
}

const VideoFeed: React.FC<VideoFeedProps> = ({ category, getAuthHeaders, toggleBookmark, savedVideoUuids }) => {
  const [videos, setVideos] = useState<Video[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useState(0);

  // Pagination state
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [isFetchingMore, setIsFetchingMore] = useState(false);

  useEffect(() => {
    const loadVideos = async (pageNum: number) => {
      if(pageNum === 1) {
        setIsLoading(true);
        setVideos([]);
      } else {
        setIsFetchingMore(true);
      }
      setError(null);
      try {
        const fetchedVideos = await fetchFeed(category, pageNum, VIDEOS_PER_PAGE, getAuthHeaders());
        if (fetchedVideos.length === 0 && pageNum === 1) {
          setError(`No videos found in the "${category}" category.`);
        }
        if (fetchedVideos.length < VIDEOS_PER_PAGE) {
          setHasMore(false);
        }
        setVideos(prev => pageNum === 1 ? fetchedVideos : [...prev, ...fetchedVideos]);
      } catch (err) {
        console.error(`Failed to fetch videos for category ${category}:`, err);
        setError('Could not load videos. Please try another category.');
      } finally {
        setIsLoading(false);
        setIsFetchingMore(false);
      }
    };

    setPage(1);
    setHasMore(true);
    setCurrentIndex(0);
    loadVideos(1);
  }, [category, getAuthHeaders]);


  useEffect(() => {
    // Pre-fetch next page when user gets close to the end
    if (currentIndex >= videos.length - 2 && hasMore && !isFetchingMore) {
      const nextPage = page + 1;
      setPage(nextPage);
      const loadMore = async () => {
        setIsFetchingMore(true);
        try {
          const fetchedVideos = await fetchFeed(category, nextPage, VIDEOS_PER_PAGE, getAuthHeaders());
           if (fetchedVideos.length < VIDEOS_PER_PAGE) {
            setHasMore(false);
          }
          setVideos(prev => [...prev, ...fetchedVideos]);
        } catch (err) {
            console.error('Failed to pre-fetch videos:', err);
        } finally {
            setIsFetchingMore(false);
        }
      };
      loadMore();
    }
  }, [currentIndex, videos.length, hasMore, isFetchingMore, page, category, getAuthHeaders]);


  const handleSwipe = (dir: 'up' | 'down') => {
    if (dir === 'up') {
      if (currentIndex < videos.length - 1) {
        setDirection(1);
        setCurrentIndex(currentIndex + 1);
      }
    } else {
      if (currentIndex > 0) {
        setDirection(-1);
        setCurrentIndex(currentIndex - 1);
      }
    }
  };

  const swipeHandlers = useSwipeable({
    onSwipedUp: () => handleSwipe('up'),
    onSwipedDown: () => handleSwipe('down'),
    preventScrollOnSwipe: true,
    trackMouse: true,
  });

  const variants = {
    enter: (direction: number) => ({
      y: direction > 0 ? '100%' : '-100%',
      opacity: 0,
    }),
    center: {
      y: 0,
      opacity: 1,
    },
    exit: (direction: number) => ({
      y: direction < 0 ? '100%' : '-100%',
      opacity: 0,
    }),
  };

  const currentVideo = useMemo(() => videos[currentIndex], [videos, currentIndex]);
  const isBookmarked = useMemo(() => savedVideoUuids.includes(currentVideo?.uuid), [savedVideoUuids, currentVideo]);

  if (isLoading) {
    return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  }

  if (error) {
    return <div className="h-full flex items-center justify-center text-center text-red-400 p-4">{error}</div>;
  }

  if (videos.length === 0) {
    return <div className="h-full flex items-center justify-center text-gray-400">No videos available.</div>;
  }

  return (
    <div {...swipeHandlers} className="h-full w-full bg-black relative touch-none overflow-hidden">
      <AnimatePresence initial={false} custom={direction}>
        <motion.div
          key={currentIndex}
          custom={direction}
          variants={variants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{
            y: { type: "spring", stiffness: 300, damping: 30 },
            opacity: { duration: 0.2 }
          }}
          className="absolute h-full w-full"
        >
          <VideoCard
            video={currentVideo}
            isPlaying={true}
            getAuthHeaders={getAuthHeaders}
            toggleBookmark={toggleBookmark}
            isBookmarked={isBookmarked}
          />
        </motion.div>
      </AnimatePresence>
    </div>
  );
};

export default VideoFeed;