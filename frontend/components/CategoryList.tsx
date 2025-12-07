
import React, { useState, useEffect } from 'react';
import { fetchCategories } from '../services/apiService';
import Spinner from './Spinner';

interface CategoryListProps {
  onSelectCategory: (category: string) => void;
  getAuthHeaders: () => HeadersInit;
}

const CategoryList: React.FC<CategoryListProps> = ({ onSelectCategory, getAuthHeaders }) => {
  const [categories, setCategories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadCategories = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const fetchedCategories = await fetchCategories(getAuthHeaders());
        setCategories(fetchedCategories);
      } catch (err) {
        console.error('Failed to fetch categories:', err);
        setError('Could not load categories. Please try again later.');
      } finally {
        setIsLoading(false);
      }
    };
    loadCategories();
  }, [getAuthHeaders]);

  if (isLoading) {
    return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  }

  if (error) {
    return <div className="h-full flex items-center justify-center text-red-400 p-4">{error}</div>;
  }

  return (
    <div className="p-4 h-full overflow-y-auto">
      <h1 className="text-2xl font-bold mb-6 text-center text-white">Categories</h1>
      {categories.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {categories.map((category) => (
            <button
              key={category}
              onClick={() => onSelectCategory(category)}
              className="p-4 bg-gray-800 rounded-lg text-white font-semibold shadow-lg hover:bg-gray-700 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              {category}
            </button>
          ))}
        </div>
      ) : (
        <p className="text-center text-gray-400">No categories found.</p>
      )}
    </div>
  );
};

export default CategoryList;