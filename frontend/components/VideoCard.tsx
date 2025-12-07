import React, { useState, useEffect, useRef } from 'react';
import { fetchStreamableUrl } from '../services/apiService';
import type { Video } from '../types';
import Spinner from './Spinner';

interface VideoCardProps {
  video: Video;
  isPlaying: boolean;
  getAuthHeaders: () => HeadersInit;
  toggleBookmark: (video: Video) => Promise<void>;
  isBookmarked: boolean;
}

const VideoCard: React.FC<VideoCardProps> = ({ video, isPlaying, getAuthHeaders, toggleBookmark, isBookmarked }) => {
  const [isMuted, setIsMuted] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [streamableUrl, setStreamableUrl] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let isMounted = true;
    const getStream = async () => {
      if (!video?.uuid) return;

      setIsLoading(true);
      setError(null);
      setStreamableUrl(null);

      try {
        const url = await fetchStreamableUrl(video.uuid, getAuthHeaders());
        if (isMounted) {
          setStreamableUrl(url);
        }
      } catch (err) {
        console.error("Failed to get streamable URL:", err);
        if (isMounted) {
          setError("Video could not be loaded.");
          setIsLoading(false);
        }
      }
    };

    getStream();

    return () => {
      isMounted = false;
    };
  }, [video?.uuid, getAuthHeaders]);


  useEffect(() => {
    const videoElement = videoRef.current;
    if (videoElement && streamableUrl) {
      if (isPlaying) {
        videoElement.play().catch(e => {
          console.warn("Autoplay was prevented:", e.name);
          // If autoplay fails, it's often due to browser policy. Muting and trying again is a common workaround.
          if (!videoElement.muted) {
            setIsMuted(true);
            videoElement.muted = true;
            videoElement.play().catch(err => console.error("Could not play video even when muted:", err));
          }
        });
      } else {
        videoElement.pause();
      }
    }
  }, [isPlaying, streamableUrl]);


  const toggleMute = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsMuted(!isMuted);
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
    }
  };

  const handleBookmarkClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      toggleBookmark(video);
  }


  return (
    <div className="relative h-full w-full bg-black flex items-center justify-center" onClick={toggleMute}>
      {(isLoading || !streamableUrl) && <div className="absolute z-10"><Spinner /></div>}
       {error && <div className="absolute z-10 text-center text-red-400 p-4 bg-black/50 rounded-lg">{error}</div>}

      {streamableUrl && (
        <video
          ref={videoRef}
          src={streamableUrl}
          className={`h-full w-full object-contain transition-opacity duration-300 ${isLoading ? 'opacity-0' : 'opacity-100'}`}
          loop
          playsInline
          muted={isMuted}
          onCanPlay={() => setIsLoading(false)}
          onWaiting={() => setIsLoading(true)}
          onError={() => {
              setIsLoading(false);
              setError("This video format may not be supported on your device.");
          }}
        />
      )}

      <div className="absolute bottom-0 left-0 right-0 p-4 pb-8 bg-gradient-to-t from-black/70 to-transparent">
        <div className="flex justify-between items-end">
          <div className="text-white">
            <p className="font-bold text-lg drop-shadow-md">{`@${video.category}`}</p>
            <p className="text-sm drop-shadow-md">{video.custom_caption || '...'}</p>
          </div>
          <div className="flex flex-col space-y-4">
            <button onClick={handleBookmarkClick} className="text-white text-center flex flex-col items-center">
                <div className={`p-3 rounded-full bg-black/40 ${isBookmarked ? 'text-yellow-400' : ''}`}>
                    <svg className="w-8 h-8" fill={isBookmarked ? "currentColor" : "none"} stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" /></svg>
                </div>
            </button>
            <button onClick={toggleMute} className="text-white text-center flex flex-col items-center">
               <div className="p-3 rounded-full bg-black/40">
                  {isMuted ?
                    <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" clipRule="evenodd" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" /></svg>
                    :
                    <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" /></svg>
                  }
               </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default VideoCard;
