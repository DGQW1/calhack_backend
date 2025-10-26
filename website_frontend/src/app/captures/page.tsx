'use client';

import React, { useEffect } from 'react';
import { usePageTitle } from '@/lib/PageTitleContext';

/**
 * This is the main component for the "Captures" page.
 * It displays a grid of captured lecture folders.
 * Per project conventions, it is exported as the default 'App' component.
 */

export default function App() {
  const { setPageTitle } = usePageTitle();

  useEffect(() => {
    setPageTitle('Captures');
  }, [setPageTitle]);
  
  // An array of mock capture folders to demonstrate the layout
  // Each folder contains assets related to a single lecture or session
  const mockCaptures = [
    { 
      id: 1, 
      title: 'CS 101: Intro to Algorithms', 
      videoCount: 1,
      noteCount: 3,
      keyFrameCount: 12,
      transcriptCount: 1
    },
    { 
      id: 2, 
      title: 'PHYS 202: Quantum Mechanics', 
      videoCount: 1,
      noteCount: 5,
      keyFrameCount: 20,
      transcriptCount: 1
    },
    { 
      id: 3, 
      title: 'HIST 300: The Roman Republic', 
      videoCount: 1,
      noteCount: 2,
      keyFrameCount: 8,
      transcriptCount: 1
    },
  ];

  return (
    // Removed bg-white and min-h-screen to inherit background from layout
    <div className="text-gray-900 p-6 sm:p-10 font-inter">
      <div className="max-w-7xl mx-auto">
        
        {/* Capture Folders Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          
          {/* Map over mock capture data to create folder cards */}
          {mockCaptures.map((capture) => (
            <div 
              key={capture.id} 
              className="bg-white rounded-lg shadow-md overflow-hidden transition-all hover:shadow-lg"
            >
              {/* Aspect-ratio box for the folder icon placeholder */}
              <div className="aspect-video bg-gray-200 flex items-center justify-center">
                {/* Simple folder icon */}
                <svg className="w-16 h-16 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                </svg>
              </div>
              
              {/* Folder Information */}
              <div className="p-4">
                <p className="font-semibold text-gray-800 truncate" title={capture.title}>
                  {capture.title}
                </p>
                <p className="text-sm text-gray-500 mt-1">
                  {capture.videoCount} Video, {capture.noteCount} Notes
                </p>
                <p className="text-sm text-gray-500">
                  {capture.transcriptCount} Transcript, {capture.keyFrameCount} Keyframes
                </p>
              </div>
            </div>
          ))}

          {/* A card to indicate adding a new capture session */}
          <div className="aspect-video bg-transparent border-2 border-dashed border-gray-300 rounded-lg flex items-center justify-center text-gray-400 hover:border-blue-500 hover:text-blue-500 transition-colors cursor-pointer">
            <div className="text-center">
              <svg className="w-10 h-10 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path>
              </svg>
              <span className="mt-2 block text-sm font-medium">Add New Capture</span>
            </div>
          </div>

        </div>
        
      </div>
    </div>
  );
}