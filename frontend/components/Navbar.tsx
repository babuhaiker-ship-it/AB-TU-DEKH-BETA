import React from 'react';
import type { Screen } from '../types';

interface NavbarProps {
  activeScreen: Screen;
  setActiveScreen: (screen: Screen) => void;
  onProfileClick: () => void;
  onSavedClick: () => void;
}

const NavButton: React.FC<{
  label: string;
  // FIX: Replaced JSX.Element with React.ReactElement to resolve "Cannot find namespace 'JSX'" error.
  icon: React.ReactElement;
  isActive: boolean;
  onClick: () => void;
}> = ({ label, icon, isActive, onClick }) => (
  <button
    onClick={onClick}
    className={`flex flex-col items-center justify-center w-full pt-2 pb-1 transition-colors duration-200 ${
      isActive ? 'text-white' : 'text-gray-400 hover:text-white'
    }`}
  >
    {icon}
    <span className={`text-xs mt-1 ${isActive ? 'font-bold' : ''}`}>{label}</span>
  </button>
);

const Navbar: React.FC<NavbarProps> = ({ activeScreen, setActiveScreen, onProfileClick, onSavedClick }) => {
  const handleNavClick = (screen: Screen) => {
    if (screen === 'profile') {
      onProfileClick();
    }
    if (screen === 'saved') {
      onSavedClick();
    }
    setActiveScreen(screen);
  };

  return (
    <nav className="w-full bg-black/80 backdrop-blur-sm border-t border-gray-700/50">
      <div className="flex justify-around max-w-lg mx-auto">
        <NavButton
          label="Home"
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" /></svg>}
          isActive={activeScreen === 'feed'}
          onClick={() => handleNavClick('feed')}
        />
        <NavButton
          label="Categories"
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>}
          isActive={activeScreen === 'categories'}
          onClick={() => handleNavClick('categories')}
        />
        <NavButton
          label="Saved"
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" /></svg>}
          isActive={activeScreen === 'saved'}
          onClick={() => handleNavClick('saved')}
        />
        <NavButton
          label="Profile"
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>}
          isActive={activeScreen === 'profile'}
          onClick={() => handleNavClick('profile')}
        />
      </div>
    </nav>
  );
};

export default Navbar;