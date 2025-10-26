import { useState, useRef, useEffect } from 'react';
import { sendMessageToClaude, ChatMessage as ApiChatMessage } from '@/services/claudeService';

type Message = {
  id: string;
  content: string;
  sender: 'user' | 'bot';
  timestamp: Date;
};

type ChatBoxProps = {};

export default function ChatBox({}: ChatBoxProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [apiChatHistory, setApiChatHistory] = useState<ApiChatMessage[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Add initial bot message
  useEffect(() => {
    const initialMessage = `Hello! I'm here to help you recall past presentations. What would you like to see?`;
    
    const botMessage: Message = {
      id: Date.now().toString(),
      content: initialMessage,
      sender: 'bot',
      timestamp: new Date(),
    };
    
    setMessages([botMessage]);
    
    // Add this message to the API chat history
    setApiChatHistory([{
      role: 'assistant',
      content: initialMessage
    }]);
  }, []);

  // Don't auto-scroll to bottom of messages on initial load
  useEffect(() => {
    // Only auto-scroll when user sends a message or gets a response
    if (messages.length > 1) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!inputValue.trim()) return;
    
    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue,
      sender: 'user',
      timestamp: new Date(),
    };
    
    // Add message to UI immediately
    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    
    // Add user message to API chat history
    const updatedChatHistory = [
      ...apiChatHistory, 
      { role: 'user', content: inputValue } as ApiChatMessage
    ];
    
    try {
      // Call Claude API
      const claudeResponse = await sendMessageToClaude(
        inputValue,
        apiChatHistory,
        "summarizing notes and past presentations for user queries"
      );
      
      // Create bot message from Claude's response
      const botResponse: Message = {
        id: Date.now().toString(),
        content: claudeResponse,
        sender: 'bot',
        timestamp: new Date(),
      };
      
      // Update UI with bot response
      setMessages(prev => [...prev, botResponse]);
      
      // Update API chat history with both messages
      setApiChatHistory([
        ...updatedChatHistory,
        { role: 'assistant', content: claudeResponse }
      ]);
    } catch (error) {
      console.error('Error getting response from Claude:', error);
      
      // Add error message
      const errorMessage: Message = {
        id: Date.now().toString(),
        content: "I'm sorry, I encountered an error. Please try again.",
        sender: 'bot',
        timestamp: new Date(),
      };
      
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-96 border border-gray-300 rounded-xl flex flex-col bg-gray-50">
      <div className="p-4 bg-[#DE7356] text-white rounded-t-xl">
        <h3 className="font-medium">Meet Kant! Your Recall Assistant</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div 
            key={message.id} 
            className={`max-w-3/4 p-3 rounded-lg ${
              message.sender === 'user' 
                ? 'bg-[#DE7356] text-white ml-auto' 
                : 'bg-gray-200 text-gray-800'
            }`}
          >
            {message.content}
          </div>
        ))}
        
        {isLoading && (
          <div className="bg-gray-200 text-gray-800 p-3 rounded-lg max-w-3/4 flex items-center space-x-2">
            <div className="w-2 h-2 bg-gray-600 rounded-full animate-bounce"></div>
            <div className="w-2 h-2 bg-gray-600 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
            <div className="w-2 h-2 bg-gray-600 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSendMessage} className="p-4 border-t border-gray-300 flex">
        <input
          type="text"
          className="flex-1 border border-gray-300 rounded-l-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-[#DE7356]"
          placeholder="Ask about summaries, slides, presentations, transcriptions..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          autoFocus={false}
        />
        <button
          type="submit"
          className="bg-[#DE7356] text-white px-4 py-2 rounded-r-lg hover:bg-[#C26B56] focus:outline-none focus:ring-2 focus:ring-[#DE7356]"
          disabled={isLoading || !inputValue.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
} 