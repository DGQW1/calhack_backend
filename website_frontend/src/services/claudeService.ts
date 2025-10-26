import Anthropic from '@anthropic-ai/sdk';

// Initialize the Anthropic client with API key from environment variables
const anthropic = new Anthropic({
  apiKey: process.env.NEXT_PUBLIC_ANTHROPIC_API_KEY,
  dangerouslyAllowBrowser: true, // Required for browser environments
});

// Type for the chat history
export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};

/**
 * Send a message to Claude and get a response
 * @param userMessage - The user's message
 * @param chatHistory - Previous chat history (optional)
 * @param context - Additional context information (optional)
 * @returns The assistant's response
 */
export async function sendMessageToClaude(
  userMessage: string,
  chatHistory: ChatMessage[] = [],
  context?: string
): Promise<string> {
  // Check if API key is available
  if (!process.env.NEXT_PUBLIC_ANTHROPIC_API_KEY) {
    console.error('Anthropic API key is missing from environment variables');
    return "I'm sorry, the assistant is not properly configured. Please check the API key.";
  }

  try {
    // Prepare the messages array for Anthropic's API
    const messages = chatHistory.map(msg => ({
      role: msg.role as 'user' | 'assistant',
      content: msg.content
    }));
    
    // Add the current user message
    messages.push({ role: 'user', content: userMessage });
    
    // Add system prompt with context if provided
    const systemPrompt = context 
      ? `You are a helpful assistant providing information about ${context}. Be clear and concise in your responses.`
      : 'You are a helpful teaching assistant for algorithms and data structures.';

    // Call the Claude API
    const response = await anthropic.messages.create({
      model: 'claude-3-7-sonnet-20250219',
      max_tokens: 1024,
      system: systemPrompt,
      messages: messages,
    });

    // Extract the text response
    if (response.content[0].type === 'text') {
      return response.content[0].text;
    } else {
      return "I couldn't generate a text response. Please try again.";
    }
  } catch (error) {
    console.error('Error calling Claude API:', error);
    return "I'm sorry, I encountered an error processing your request. Please try again.";
  }
}

// Export the Anthropic client in case direct access is needed
export { anthropic }; 