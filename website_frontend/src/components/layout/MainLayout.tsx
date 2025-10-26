'use client'; // This must be a client component to use state

import { ReactNode, useState } from 'react';
import Sidebar from './Sidebar'; // Correct path
import Header from './Header';   // Correct path
import { PageTitleProvider } from '@/lib/PageTitleContext';

type MainLayoutProps = {
  children: ReactNode;
};

export default function MainLayout({ children }: MainLayoutProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  const toggleSidebar = () => {
    setIsCollapsed(!isCollapsed);
  };

  return (
    <PageTitleProvider>
      <div className="flex min-h-screen bg-gray-50">
        {/* Sidebar Component */}
        <Sidebar isCollapsed={isCollapsed} onToggle={toggleSidebar} />
        
        {/* Main Content Area */}
        {/* Adjust left margin based on sidebar state with transition */}
        <div className={`flex-1 flex flex-col ${isCollapsed ? 'ml-20' : 'ml-64'} transition-all duration-300`}>
          
          {/* Sticky Header Component */}
          <div className="sticky top-0 z-10">
            <Header />
          </div>
          
          {/* Page Content */}
          <main className="flex-1 max-w-7xl mx-auto py-6 sm:px-6 lg:px-8 w-full">
            {children}
          </main>
        </div>
      </div>
    </PageTitleProvider>
  );
}

