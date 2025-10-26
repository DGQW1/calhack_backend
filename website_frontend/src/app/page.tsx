'use client';

import { useEffect } from 'react';
import ChatBox from '@/components/chat/ChatBox';
import { usePageTitle } from '@/lib/PageTitleContext';

export default function Home() {
  const { setPageTitle } = usePageTitle();

  useEffect(() => {
    setPageTitle('Dashboard');
  }, [setPageTitle]);

  return <ChatBox />;
}