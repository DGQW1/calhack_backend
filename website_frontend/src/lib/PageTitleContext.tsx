// frontend/src/lib/PageTitleContext.tsx
'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';

type PageTitleContextType = {
  pageTitle: string;
  setPageTitle: (title: string) => void;
};

const PageTitleContext = createContext<PageTitleContextType | undefined>(undefined);

export const PageTitleProvider = ({ children }: { children: ReactNode }) => {
  const [pageTitle, setPageTitle] = useState('Dashboard'); // Default title

  return (
    <PageTitleContext.Provider value={{ pageTitle, setPageTitle }}>
      {children}
    </PageTitleContext.Provider>
  );
};

export const usePageTitle = () => {
  const context = useContext(PageTitleContext);
  if (context === undefined) {
    throw new Error('usePageTitle must be used within a PageTitleProvider');
  }
  return context;
};
