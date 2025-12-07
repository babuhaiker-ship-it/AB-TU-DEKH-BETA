
import { useState, useEffect } from 'react';
import type { TelegramWebApp, TelegramUser } from '../types';

const getTelegramWebApp = (): TelegramWebApp | null => {
  if (typeof window !== 'undefined' && (window as any).Telegram && (window as any).Telegram.WebApp) {
    return (window as any).Telegram.WebApp;
  }
  return null;
};

// Mock implementation for local development outside the Telegram client
const mockWebApp: TelegramWebApp = {
  initData: 'mock_init_data_string_for_development',
  initDataUnsafe: {
    user: {
      id: 123456789,
      first_name: 'Dev',
      last_name: 'User',
      username: 'devuser',
      language_code: 'en',
      is_premium: true,
    },
  },
  ready: () => console.log('Mock WebApp: ready() called'),
  expand: () => console.log('Mock WebApp: expand() called'),
  showAlert: (message: string) => alert(`Mock Alert: ${message}`),
  HapticFeedback: {
    impactOccurred: (style) => console.log(`Mock Haptic: impactOccurred(${style})`),
    notificationOccurred: (type) => console.log(`Mock Haptic: notificationOccurred(${type})`),
    selectionChanged: () => console.log('Mock Haptic: selectionChanged()'),
  },
  close: () => console.log('Mock WebApp: close() called'),
};

export const useTelegramWebApp = () => {
  const [webApp, setWebApp] = useState<TelegramWebApp | null>(null);

  useEffect(() => {
    const app = getTelegramWebApp();
    if (app) {
      app.ready();
      app.expand();
      setWebApp(app);
    } else {
      console.warn('Telegram WebApp is not available. Using mock data for development.');
      setWebApp(mockWebApp);
    }
  }, []);

  return {
    webApp,
    user: webApp?.initDataUnsafe?.user,
    initData: webApp?.initData,
  };
};