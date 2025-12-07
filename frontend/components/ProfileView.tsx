import React from 'react';
import type { ProfileData } from '../types';
import Spinner from './Spinner';

interface ProfileViewProps {
  profileData: ProfileData | null;
  isLoading: boolean;
}

// FIX: Replaced JSX.Element with React.ReactElement to resolve "Cannot find namespace 'JSX'" error.
const ProfileStat: React.FC<{ label: string; value: string | number; icon: React.ReactElement }> = ({ label, value, icon }) => (
  <div className="bg-gray-800 p-4 rounded-lg flex items-center space-x-4">
    <div className="p-3 bg-gray-700 rounded-full">{icon}</div>
    <div>
      <p className="text-sm text-gray-400">{label}</p>
      <p className="text-xl font-bold text-white">{value}</p>
    </div>
  </div>
);

const ProfileView: React.FC<ProfileViewProps> = ({ profileData, isLoading }) => {
  if (isLoading) {
    return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  }

  if (!profileData) {
    return <div className="h-full flex items-center justify-center text-red-400">Could not load profile.</div>;
  }

  return (
    <div className="p-6 h-full overflow-y-auto text-white">
      <h1 className="text-3xl font-bold mb-8 text-center">Your Profile</h1>
      <div className="space-y-4">
        <ProfileStat
          label="Account Status"
          value={profileData.status}
          icon={<svg className="w-6 h-6 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
        />
        <ProfileStat
          label="Active Tokens"
          value={profileData.tokens}
          icon={<svg className="w-6 h-6 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v.01" /></svg>}
        />
        <ProfileStat
          label="Referrals"
          value={profileData.referrals}
          icon={<svg className="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>}
        />
      </div>
    </div>
  );
};

export default ProfileView;