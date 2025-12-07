import React, { useState, useEffect, useMemo } from 'react';
import type { Video } from '../types';
import VideoCard from './VideoCard';
import Spinner from './Spinner';
import { useSwipeable } from 'react-swipeable';
import { motion, AnimatePresence } from 'framer-motion';

interface SavedVideosProps {
  savedVideos: Video[];
  getAuthHeaders: () => HeadersInit;
  toggleBookmark: (video: Video) => Promise<void>;
}

const SavedVideos: React.FC<SavedVideosProps> = ({ savedVideos, getAuthHeaders, toggleBookmark }) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [direction, setDirection] = useState(0);

  // This effect handles the case where a video is removed from the list.
  // If the current index becomes out of bounds, it adjusts to the new last video.
  useEffect(() => {
    if (savedVideos.length > 0 && currentIndex >= savedVideos.length) {
      setCurrentIndex(savedVideos.length - 1);
    }
  }, [savedVideos, currentIndex]);

  const handleSwipe = (dir: 'up' | 'down') => {
    if (dir === 'up') {
      if (currentIndex < savedVideos.length - 1) {
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
      y: direction > 0 ? '100%' : '100%',
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

  const currentVideo = useMemo(() => {
    if (savedVideos.length > 0 && currentIndex < savedVideos.length) {
      return savedVideos[currentIndex];
    }
    return null;
  }, [currentIndex, savedVideos]);

  if (savedVideos.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 p-4 text-center">
        You have no saved videos. Bookmark videos from the feed to see them here.
      </div>
    );
  }

  return (
    <div {...swipeHandlers} className="h-full w-full bg-black relative touch-none overflow-hidden">
      <AnimatePresence initial={false} custom={direction}>
        {currentVideo ? (
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
              isBookmarked={true} // A video on this screen is always bookmarked
            />
          </motion.div>
        ) : (
           <div className="h-full flex items-center justify-center"><Spinner /></div>
        )}
      </AnimatePresence>
      <div className="absolute top-4 right-4 bg-black/50 text-white text-xs font-mono px-2 py-1 rounded-md z-10">
        {currentIndex + 1} / {savedVideos.length}
      </div>
    </div>
  );
};

export default SavedVideos;
