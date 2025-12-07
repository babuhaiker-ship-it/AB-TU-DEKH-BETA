/// <reference types="vite/client" />

// This file contains global type augmentations for the Window object.

declare global {
  interface Window {
    Telegram: {
      WebApp: import('../types').TelegramWebApp;
    };
  }
}

// Adding an empty export statement turns this file into a module,
// which is necessary for using `declare global` to augment the global scope.
export {};