// FIX: Moved the triple-slash directive to types/globals.d.ts to ensure it's loaded correctly.
// This makes TypeScript aware of `import.meta.env` and resolves related type errors.

export type Screen = 'feed' | 'categories' | 'saved' | 'profile';

export interface ProfileData {
  status: 'Premium' | 'Free';
  tokens: number;
  referrals: number;
}

export interface Video {
  uuid: string;
  custom_caption: string;
  category: string;
}

export interface TelegramUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: TelegramUser;
    [key: string]: any;
  };
  ready: () => void;
  expand: () => void;
  showAlert: (message: string) => void;
  HapticFeedback: {
    impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
    notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
    selectionChanged: () => void;
  };
  close: () => void;
  [key: string]: any;
}